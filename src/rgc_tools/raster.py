"""
rgc-raster: raster + PSTH for one unit from a *.dataset.h5 file, with trials
aligned to the stimulus blocks. Uses stimulus/blocks (written by
rgc-check-dataset --write-blocks, protocol-labelled) when present; otherwise
falls back to the generic marker decoding in rgc_tools.trials.
Optional: restrict to blocks with a given label/direction (e.g. --direction 90).
"""
import argparse
import os
import sys

import h5py
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .trials import decode_trials, align
from .blocks import load_blocks


def main():
    ap = argparse.ArgumentParser(prog="rgc-raster", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", help="a *.dataset.h5 file")
    ap.add_argument("unit", nargs="?", default="auto",
                    help="unit name, e.g. temp_2 (default: the most strongly modulated unit)")
    ap.add_argument("--tmax", type=float, help="show only 0..tmax s after the marker (default: full cycle)")
    ap.add_argument("--bin", type=float, default=0.02, help="PSTH bin in seconds (default 0.02)")
    ap.add_argument("--direction", type=float, help="use only blocks with this direction (grating protocols)")
    ap.add_argument("-o", "--out", help="output PNG (default: raster_psth_<recording>_<unit>.png next to the dataset)")
    a = ap.parse_args()
    if not os.path.isfile(a.dataset):
        sys.exit("\nERROR: file not found: %s\n" % a.dataset)

    with h5py.File(a.dataset, "r") as f:
        fs = float(f.attrs["sampling_rate_hz"])
        source = f.attrs["source_raw_file"]
        markers = f["stimulus/markers/sample"][:]
        log_start = f["stimulus/bits_raw/sample"][0]
        spikes = {u: f["spikes"][u]["spike_sample"][:].astype(np.int64) for u in f["spikes"]}
        blocks = load_blocks(f)

    if blocks:
        # trial length = block start to next block start, from the full sequence (before any filtering)
        all_on = np.array([b["start_sample"] for b in blocks])
        period = int(round(np.median(np.diff(all_on)))) if len(all_on) > 1 else int(blocks[0]["end_sample"] - all_on[0]) * 2
        if a.direction is not None:
            blocks = [b for b in blocks if abs(b["direction"] - a.direction) < 1e-6]
            if not blocks:
                sys.exit("\nERROR: no blocks with direction %g\n" % a.direction)
        on = np.array([b["start_sample"] for b in blocks]); off = np.array([b["end_sample"] for b in blocks])
        label = blocks[0]["label"] + ("" if np.isnan(blocks[0]["direction"]) else " %g deg" % blocks[0]["direction"]
                                       if a.direction is not None else " (all directions)")
        align_note = "aligned to protocol blocks (stimulus/blocks): '%s'" % label
    else:
        on, off = decode_trials(markers, fs, log_start)
        period = int(round(np.diff(on).mean()))
        align_note = "aligned to logged stimulus markers (generic decoding)"
    T = period / fs
    seg_a = (off - on).mean() / fs
    n_tr = len(on)
    t_max = a.tmax or T

    unit = a.unit
    if unit == "auto":
        edges = np.arange(0, period + 0.05 * fs, 0.05 * fs)
        best = 0
        for u, spk in spikes.items():
            if len(spk) < 200:
                continue
            tr, t = align(spk, on, period)
            M = np.array([np.histogram(t[tr == k], edges)[0] for k in range(n_tr)])
            v = M.var(0).mean()
            qi = M.mean(0).var() / v if v > 0 else 0
            if qi > best:
                best, unit = qi, u
        print("auto-selected %s (quality index %.2f)" % (unit, best))
    elif unit not in spikes:
        sys.exit("\nERROR: unit %s not in file; units are %s ... %s\n" % (unit, sorted(spikes)[0], sorted(spikes)[-1]))

    trial, t_in = align(spikes[unit], on, period)
    t_in = t_in / fs

    fig, (ax_r, ax_p) = plt.subplots(2, 1, figsize=(8, 6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    for ax in (ax_r, ax_p):
        ax.axvspan(0, seg_a, color="#f7e58c", alpha=0.4, zorder=0)
        ax.axvspan(seg_a, T, color="#c9c9c9", alpha=0.3, zorder=0)
    ax_r.eventplot([t_in[trial == k] for k in range(n_tr)], lineoffsets=np.arange(1, n_tr + 1), linelengths=0.8, color="k")
    ax_r.set_ylim(0.5, n_tr + 0.5)
    ax_r.set_ylabel("Trial")
    ax_r.set_title("%s -- %s\n%s; marked %.3f s / unmarked %.3f s, %d trials, %d spikes"
                   % (unit, source, align_note, seg_a, T - seg_a, n_tr, len(t_in)), fontsize=10)
    edges = np.arange(0, t_max + a.bin, a.bin)
    counts, _ = np.histogram(t_in, edges)
    ax_p.bar(edges[:-1], counts / (n_tr * a.bin), width=a.bin, align="edge", color="#3b6ea5")
    ax_p.set_ylabel("spikes/s (%g ms bins)" % (a.bin * 1000))
    ax_p.set_xlabel("time from block start (s)")
    ax_p.set_xlim(0, t_max)

    tag = os.path.basename(a.dataset).replace(".dataset.h5", "")
    dtag = "" if a.direction is None else "_dir%g" % a.direction
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.dataset)), "raster_psth_%s_%s%s.png" % (tag, unit, dtag))
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print("Wrote", out)


if __name__ == "__main__":
    main()

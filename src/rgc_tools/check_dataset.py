"""
rgc-check-dataset: diagnostic checks on a *.dataset.h5 file made by
rgc-build-dataset. Reads only; changes nothing. Reports:

  1. Provenance: do the sorted spikes coincide (in samples) with the raw file's
     threshold crossings? A true match is far above chance; ~chance means the
     spikes were sorted from a different recording.
  2. Heartbeat: display frame period / refresh rate from the bits heartbeat
     (values 128/160), and times where the heartbeat paused (log dropouts).
  3. Markers: interval sequence between stimulus pulses, the distinct interval
     lengths, whether the first pulse is an initialization value, whether
     intervals alternate, and any interval equal to the sum of two segment
     lengths (a dropped pulse) with the position where one would be re-inserted.
  4. Neural check: for every logged pulse and every proposed re-insertion, the
     peak raw population rate 50-300 ms after the pulse relative to the mean
     rate 600-100 ms before (a light transition gives a value well above 1).
  5. Protocol decoding (if stimulus/protocol is present): walks the expected
     block sequence against the logged pulses, labels every block, re-inserts
     dropped pulses at their nominal position, and -- with --write-blocks --
     stores the result as stimulus/blocks in the dataset file.
"""
import argparse
import os
import sys

import h5py
import numpy as np

from .blocks import decode_blocks, write_blocks
from .stimulus import read_protocol_group

HEARTBEAT_VALUE = 160


def neural_ratio(t, s, fs, bin_s=0.01):
    w = (s[np.searchsorted(s, t - int(0.6 * fs)):np.searchsorted(s, t + int(0.3 * fs))] - t) / fs
    pre = np.histogram(w, np.arange(-0.6, -0.1 + 1e-9, bin_s))[0].mean()
    post = np.histogram(w, np.arange(0.05, 0.3 + 1e-9, bin_s))[0].max()
    return post / pre if pre > 0 else np.nan


def check(path, write=False):
    with h5py.File(path, "r") as f:
        if "stimulus/markers" not in f or "spikes" not in f:
            sys.exit("\nERROR: %s is not a dataset file made by rgc-build-dataset\n" % path)
        fs = float(f.attrs["sampling_rate_hz"])
        n_samples = int(f.attrs["n_samples"])
        bits_s = f["stimulus/bits_raw/sample"][:]
        bits_v = f["stimulus/bits_raw/value"][:]
        mk = f["stimulus/markers/sample"][:]
        raw = np.sort(f["raw_threshold_crossings"]["sample"][:])
        spikes = np.concatenate([f["spikes"][u]["spike_sample"][:] for u in f["spikes"]])
        print("%s\n  raw %s | spikes %s" % (path, f.attrs["source_raw_file"], f.attrs["source_spike_file"]))

    verdict = []

    # 1. provenance
    occ = np.zeros(n_samples + 3, bool)
    for d in (-2, -1, 0, 1, 2):
        occ[np.clip(raw + d, 0, len(occ) - 1)] = True
    hit, chance = occ[np.clip(spikes, 0, len(occ) - 1)].mean(), occ.mean()
    match = hit > 2.5 * chance
    print("\n1. PROVENANCE: %.1f%% of %d sorted spikes within 2 samples of a raw threshold crossing (chance %.1f%%) -> %s"
          % (100 * hit, len(spikes), 100 * chance, "MATCH" if match else "NO MATCH"))
    verdict.append("spikes %s this raw file" % ("belong to" if match else "DO NOT belong to"))

    if len(bits_s) == 0:
        print("\n2-4. no bits log in this recording (no stimulus markers)")
        print("\nVERDICT: " + "; ".join(verdict))
        return

    # 2. heartbeat
    hb = np.sort(bits_s[bits_v == HEARTBEAT_VALUE])
    dt = np.diff(hb) / fs
    med = np.median(dt)
    frame = dt[(dt > 0.5 * med) & (dt < 1.5 * med)].mean() / 2
    drop = hb[:-1][dt > 1.5 * med] / fs
    print("\n2. HEARTBEAT: %d ticks, one per 2 frames -> frame %.4f ms, refresh %.3f Hz; log start %.4f s, end %.4f s"
          % (len(hb), frame * 1000, 1 / frame, bits_s[0] / fs, bits_s[-1] / fs))
    print("   heartbeat pauses (log dropouts) at: %s s" % np.round(drop, 3).tolist())

    # 3. markers
    print("\n3. MARKERS: %d stimulus pulses (bits == 0)" % len(mk))
    if len(mk) < 3:
        print("\nVERDICT: " + "; ".join(verdict + ["too few markers to analyse"]))
        return
    t = mk / fs
    init = (mk[0] - bits_s[0]) / fs < 0.01
    print("   first pulse at %.4f s, %.1f ms after log start -> %s"
          % (t[0], (mk[0] - bits_s[0]) / fs * 1000,
             "coincides with log start: initialization, not a stimulus event" if init else "not at log start"))
    g = np.diff(t)
    levels = []
    for x in np.sort(g):
        if not levels or abs(x - levels[-1][0]) > 0.02 * levels[-1][0]:
            levels.append([x, 1])
        else:
            levels[-1][1] += 1
            levels[-1][0] = (levels[-1][0] * (levels[-1][1] - 1) + x) / levels[-1][1]
    print("   distinct intervals (s, count): %s" % ", ".join("%.3f x%d" % (v, n) for v, n in levels))
    print("   interval sequence (s): %s" % np.round(g, 3).tolist())
    main_levels = sorted(v for v, n in levels if n >= 3)
    proposals = []
    if len(main_levels) >= 2:
        a, b = main_levels[:2]
        alternates = True
        for i in range(1, len(g)):
            if abs(g[i] - (a + b)) < 0.03 * (a + b) or abs(g[i - 1] - (a + b)) < 0.03 * (a + b):
                continue
            if i == 1 and init:
                continue
            prev_short = abs(g[i - 1] - a) < abs(g[i - 1] - b)
            expect = b if prev_short else a
            if abs(g[i] - expect) > 0.03 * (a + b):
                alternates = False
        print("   dominant segments: %.4f s (%.1f frames) and %.4f s (%.1f frames); pair = %.4f s = %.1f frames; alternate: %s"
              % (a, a / frame, b, b / frame, a + b, (a + b) / frame, "yes" if alternates else "NO -- inspect the sequence"))
        for i in np.where(np.abs(g - (a + b)) < 0.03 * (a + b))[0]:
            prev = g[i - 1] if i > 0 else None
            if prev is not None:
                seg = b if abs(prev - a) < abs(prev - b) else a
            else:
                seg = a if abs(g[i + 1] - a) < abs(g[i + 1] - b) else b
            new = mk[i] + int(round(seg * fs))
            proposals.append(new)
            print("   DROPPED PULSE suspected between markers %d and %d (%.3f -> %.3f s, gap %.3f = %.3f + %.3f): "
                  "re-insert at %.4f s (sample %d)" % (i, i + 1, t[i], t[i + 1], g[i], a, b, new / fs, new))
        if not proposals:
            print("   no dropped pulses suspected")
        n_pulses = len(mk) - (1 if init else 0) + len(proposals)
        verdict.append("%d stimulus pulses = %d trials of %.1f + %.1f frames" % (n_pulses, n_pulses // 2, a / frame, b / frame))
        verdict.append("%d dropped pulse(s)" % len(proposals) if proposals else "no dropped pulses")
        if not alternates:
            verdict.append("WARNING: intervals do not alternate cleanly")
    else:
        print("   fewer than two recurring interval lengths -- no alternation structure to check")
        verdict.append("%d pulses, no repeating two-segment structure" % len(mk))
    odd = [i for i in range(len(g)) if not any(abs(g[i] - v) < 0.03 * v for v, n in levels if n >= 3)
           and not (len(main_levels) >= 2 and abs(g[i] - sum(main_levels[:2])) < 0.03 * sum(main_levels[:2]))]
    if odd:
        print("   irregular intervals at marker index %s: %s s%s" % (odd, np.round(g[odd], 3).tolist(),
              "  (index 0 = initialization gap)" if odd == [0] and init else ""))

    # 4. neural check
    r = np.array([neural_ratio(x, raw, fs) for x in mk])
    print("\n4. NEURAL CHECK (peak population rate 50-300 ms after pulse / mean 600-100 ms before):")
    print("   logged pulses: median %.2f, min %.2f (at %.3f s), max %.2f" % (np.nanmedian(r), np.nanmin(r), t[np.nanargmin(r)], np.nanmax(r)))
    print("   per pulse: %s" % np.round(r, 2).tolist())
    print("   even-indexed pulses: median %.2f; odd-indexed: median %.2f" % (np.nanmedian(r[::2]), np.nanmedian(r[1::2])))
    for s_new in proposals:
        rr = neural_ratio(s_new, raw, fs)
        print("   proposed re-inserted pulse at %.4f s: ratio %.2f (%s)" % (s_new / fs, rr,
              "consistent with a real transition" if rr > 1.3 else "NO transient -- check this one"))
    weak = np.where(r < 1.2)[0]
    if len(weak):
        verdict.append("WARNING: %d pulse(s) without a neural transient (index %s)" % (len(weak), weak.tolist()))

    # 5. protocol decoding
    with h5py.File(path, "r+" if write else "r") as f:
        proto = read_protocol_group(f)
        if proto is None:
            print("\n5. PROTOCOL: none stored (rebuild with rgc-build-dataset --stimulus Protocol.py to enable labelled blocks)")
        else:
            print("\n5. PROTOCOL: %s from %s (%d parameters)" % (proto["class_name"], proto["source_file"], len(json_keys(proto))))
            print("   " + str(proto.get("marker_semantics", "")))
            blocks, report = decode_blocks(f)
            for line in report:
                print("   " + line)
            if blocks:
                labels = sorted(set((b["label"], b["direction"]) for b in blocks))
                print("   blocks: %d; labels: %s" % (len(blocks), ", ".join(
                    "%s%s" % (l, "" if np.isnan(d) else " %g" % d) for l, d in labels)))
                for b in blocks[:3]:
                    print("   block %d %s%s: %.4f -> %.4f s%s" % (b["block_index"], b["label"], "" if np.isnan(b["direction"]) else " dir %g" % b["direction"],
                          b["start_sample"] / fs, b["end_sample"] / fs, " (inferred)" if b["start_inferred"] or b["end_inferred"] else ""))
                print("   ...")
                n_inf = sum(b["start_inferred"] + b["end_inferred"] for b in blocks)
                verdict.append("protocol %s: %d blocks decoded, %d pulse(s) re-inserted" % (proto["class_name"], len(blocks), n_inf))
                if write:
                    write_blocks(f, blocks, report)
                    print("   wrote stimulus/blocks (%d rows) to %s" % (len(blocks), path))
                    verdict.append("stimulus/blocks written")
                else:
                    print("   (run with --write-blocks to store this decoding as stimulus/blocks)")

    print("\nVERDICT: " + "; ".join(verdict))


def json_keys(proto):
    import json
    try:
        return json.loads(proto.get("parameters_json", "{}"))
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser(prog="rgc-check-dataset", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dataset", nargs="?", help="a *.dataset.h5 file made by rgc-build-dataset")
    ap.add_argument("--gui", action="store_true", help="choose the file with a file dialog")
    ap.add_argument("--write-blocks", action="store_true", help="store the protocol-based decoding as stimulus/blocks in the file")
    a = ap.parse_args()
    if a.gui or a.dataset is None:
        import tkinter as tk
        from tkinter import filedialog
        tk.Tk().withdraw()
        a.dataset = filedialog.askopenfilename(title="Choose a *.dataset.h5 file",
                                               filetypes=[("dataset", "*.dataset.h5"), ("HDF5", "*.h5"), ("all", "*")])
        if not a.dataset:
            sys.exit("cancelled")
    if not os.path.isfile(a.dataset):
        sys.exit("\nERROR: file not found: %s\n" % a.dataset)
    check(a.dataset, write=a.write_blocks)


if __name__ == "__main__":
    main()

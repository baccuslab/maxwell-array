"""
rgc-build-dataset: combine a MaxLab raw recording (.raw.h5) and SpyKING CIRCUS
sorted spikes (.result-merged.hdf5, or a CSV with unit + spike_sample columns)
into one small *.dataset.h5 file on a single sample clock.

The dataset records what was logged; it does not interpret the stimulus
markers. Use rgc-check-dataset for that.

Layout of the output file:
  /                         attrs: source files, recording/chip metadata, sample convention
  /stimulus/bits_raw        every row of the raw file's bits/0000 log (sample, time_sec, value)
  /stimulus/markers         rows with value == 0, exactly as logged (sample, time_sec)
  /stimulus/protocol        (with --stimulus) the stimulus definition: verbatim source, parsed
                            parameters, marker semantics, expected block sequence; rig values
  /raw_threshold_crossings  the raw file's online spike detections (sample, channel, amplitude)
  /electrode_mapping        recording channel -> electrode id, x, y (um)
  /spikes/<unit>/           spike_sample, spike_time_sec, amplitude

Sample convention: sample i of the raw traces has frame number frame_nos[0] + i.
Everything in the file uses that sample index.
"""
import argparse
import csv
import json
import datetime
import os
import sys

import h5py
import numpy as np

from .stimulus import parse_protocol, write_protocol_group

STR = h5py.special_dtype(vlen=str)


def fail(msg):
    sys.exit("\nERROR: %s\n" % msg)


def read_raw(path):
    with h5py.File(path, "r") as f:
        if "data_store/data0000" not in f:
            fail("%s does not look like a MaxLab raw file (no data_store/data0000 group)" % path)
        d = f["data_store/data0000"]
        fr = d["groups/routed/frame_nos"]
        info = dict(
            sampling_rate_hz=float(d["settings/sampling"][()][0]),
            first_frame_no=int(fr[0]),
            n_samples=int(d["groups/routed/raw"].shape[1]),
            n_channels=int(d["groups/routed/raw"].shape[0]),
            frame_nos_contiguous=bool(int(fr[-1]) - int(fr[0]) + 1 == fr.shape[0]),
            recording_start_ms=int(d["start_time"][()][0]),
            recording_stop_ms=int(d["stop_time"][()][0]),
            lsb_volts=float(d["settings/lsb"][()][0]),
            gain=float(d["settings/gain"][()][0]),
            hpf_hz=float(d["settings/hpf"][()][0]),
            spike_threshold=float(d["settings/spike_threshold"][()][0]),
        )
        for key, name in [("wellplate/version", "chip_type"), ("wellplate/id", "chip_id"),
                          ("wellplate/well000/name", "well_name"), ("wellplate/well000/Plating Date", "plating_date"),
                          ("mxw_version", "maxlab_version"), ("version", "file_format_version")]:
            if key in f:
                v = f[key][()]
                v = v[0] if hasattr(v, "__len__") else v
                info[name] = v.decode() if isinstance(v, bytes) else v
        empty = []
        for k in ["data_store/data0000/events", "assay/inputs", "environment/temperature", "bits"]:
            if k in f:
                o = f[k]
                if (isinstance(o, h5py.Group) and len(o) == 0) or (isinstance(o, h5py.Dataset) and o.shape == (0,)):
                    empty.append(k)
        info["empty_groups_in_raw"] = ",".join(empty)
        if "bits/0000" in f:
            bits = f["bits/0000"][:]
        else:
            bits = np.zeros(0, dtype=[("frameno", "<i8"), ("bits", "<i4")])
            print("WARNING: no bits/0000 in the raw file -- no stimulus markers (baseline recording?)")
        raw_spk = d["spikes"][:]
        mapping = d["settings/mapping"][:]
    out = np.empty(len(raw_spk), dtype=[("sample", "<i8"), ("channel", "<i4"), ("amplitude", "<f4")])
    out["sample"] = raw_spk["frameno"] - info["first_frame_no"]
    out["channel"] = raw_spk["channel"]
    out["amplitude"] = raw_spk["amplitude"]
    return info, bits, out, mapping


def read_spikes(path, fs):
    units = {}
    if path.lower().endswith((".hdf5", ".h5")):
        with h5py.File(path, "r") as f:
            if "spiketimes" not in f:
                fail("%s has no 'spiketimes' group -- expected a SpyKING CIRCUS .result-merged.hdf5 file" % path)
            for u in f["spiketimes"]:
                smp = f["spiketimes"][u][:].astype(np.int64)
                amp = f["amplitudes"][u][:] if "amplitudes" in f and u in f["amplitudes"] else None
                o = np.argsort(smp)
                units[u] = (smp[o], amp[o].astype(np.float32) if amp is not None else None)
        fmt = "spyking-circus result: spiketimes in samples; amplitude = (template amplitude, derivative amplitude)"
    elif path.lower().endswith(".csv"):
        with open(path) as fh:
            r = csv.DictReader(fh)
            cols = r.fieldnames or []
            if "spike_sample" not in cols and "spike_time_sec" not in cols:
                fail("CSV %s needs a 'spike_sample' (or 'spike_time_sec') column; found columns: %s" % (path, cols))
            ucol = "unit" if "unit" in cols else cols[0]
            acol = next((c for c in cols if "amplitude" in c.lower()), None)
            tmp = {}
            for row in r:
                s = int(row["spike_sample"]) if "spike_sample" in cols else int(round(float(row["spike_time_sec"]) * fs))
                tmp.setdefault(row[ucol], []).append((s, float(row[acol]) if acol else np.nan))
        for u, v in tmp.items():
            a = np.array(v)
            o = np.argsort(a[:, 0])
            units[u] = (a[o, 0].astype(np.int64), a[o, 1].astype(np.float32) if acol else None)
        fmt = "csv: spike_sample column" if "spike_sample" in cols else "csv: spike_time_sec * sampling rate"
    else:
        fail("spike file must be a SpyKING CIRCUS .result-merged.hdf5 or a .csv, got %s" % path)
    if not units:
        fail("no units found in %s" % path)
    return units, fmt


def unit_key(u):
    tail = u.split("_")[-1]
    return int(tail) if tail.isdigit() else 0


def build(raw_path, spk_path, out_path, stim_path=None, rig_path=None):
    info, bits, raw_spk, mapping = read_raw(raw_path)
    fs = info["sampling_rate_hz"]
    units, spike_fmt = read_spikes(spk_path, fs)
    proto = parse_protocol(stim_path) if stim_path else None
    rig = json.load(open(rig_path)) if rig_path else None
    fps = float(rig["nominal_frame_rate_hz"]) if rig and rig.get("nominal_frame_rate_hz") else 60.0
    bits_sample = bits["frameno"] - info["first_frame_no"]
    marker_sample = bits_sample[bits["bits"] == 0]

    with h5py.File(out_path, "w") as f:
        f.attrs["source_raw_file"] = os.path.basename(raw_path)
        f.attrs["source_raw_path"] = os.path.abspath(raw_path)
        f.attrs["source_spike_file"] = os.path.basename(spk_path)
        f.attrs["source_spike_path"] = os.path.abspath(spk_path)
        f.attrs["source_spike_format"] = spike_fmt
        f.attrs["source_stimulus_file"] = os.path.basename(stim_path) if stim_path else ""
        f.attrs["source_rig_file"] = os.path.basename(rig_path) if rig_path else ""
        f.attrs["created"] = datetime.datetime.now().isoformat(timespec="seconds")
        f.attrs["created_by"] = "rgc-build-dataset"
        for k, v in info.items():
            f.attrs[k] = v
        f.attrs["duration_sec"] = info["n_samples"] / fs
        f.attrs["sample_convention"] = "sample = frameno - first_frame_no; time_sec = sample / sampling_rate_hz"

        g = f.create_group("stimulus")
        b = g.create_group("bits_raw")
        b.create_dataset("sample", data=bits_sample)
        b.create_dataset("time_sec", data=bits_sample / fs)
        b.create_dataset("value", data=bits["bits"])
        b.attrs["description"] = "every row of the raw file's bits/0000 digital-input log (value after each transition)"
        m = g.create_group("markers")
        m.create_dataset("sample", data=marker_sample)
        m.create_dataset("time_sec", data=marker_sample / fs)
        m.attrs["description"] = ("bits_raw rows with value == 0, as logged, no interpretation: the stimulus program pulses "
                                  "this line at stimulus events; onset/offset meaning, dropped pulses and trial structure "
                                  "must be established separately (rgc-check-dataset)")
        m.attrs["n_markers"] = len(marker_sample)
        exp_blocks = write_protocol_group(f, proto, rig, fps) if proto else []

        r = f.create_dataset("raw_threshold_crossings", data=raw_spk, compression="gzip")
        r.attrs["description"] = ("online spike detections from the raw file (data_store/data0000/spikes), threshold %.1f x noise; "
                                  "sample on the same clock as spikes/*/spike_sample" % info["spike_threshold"])
        e = f.create_dataset("electrode_mapping", data=mapping)
        e.attrs["description"] = "raw-file settings/mapping: recording channel -> electrode id and position (x, y in um)"

        s = f.create_group("spikes")
        s.attrs["n_units"] = len(units)
        s.attrs["unit_names"] = np.array(sorted(units, key=unit_key), dtype=STR)
        s.attrs["description"] = "sorted spikes per unit; spike_sample on the raw file's sample clock"
        n_total = 0
        for u, (smp, amp) in units.items():
            ug = s.create_group(u)
            ug.create_dataset("spike_sample", data=smp, compression="gzip")
            ug.create_dataset("spike_time_sec", data=smp / fs, compression="gzip")
            if amp is not None:
                ug.create_dataset("amplitude", data=amp, compression="gzip")
            ug.attrs["n_spikes"] = len(smp)
            n_total += len(smp)

    print("Wrote %s" % out_path)
    print("  raw:     %s (%.2f s, %d channels, %.0f Hz, %s, chip %s)" % (
        os.path.basename(raw_path), info["n_samples"] / fs, info["n_channels"], fs,
        info.get("chip_type", "?"), info.get("chip_id", "?")))
    print("  spikes:  %s -> %d units, %d spikes" % (os.path.basename(spk_path), len(units), n_total))
    if len(marker_sample):
        print("  markers: %d stimulus pulses (bits==0), first at %.4f s, last at %.4f s; bits log has %d rows" % (
            len(marker_sample), marker_sample[0] / fs, marker_sample[-1] / fs, len(bits)))
    if proto:
        print("  stimulus: %s (class %s, %d parameters%s)" % (proto["file_name"], proto["class_name"], len(proto["parameters"]),
              "; expects %d blocks = %d pulses" % (len(exp_blocks), 2 * len(exp_blocks)) if exp_blocks else "; marker semantics unknown"))
        if exp_blocks and len(marker_sample):
            n_logged = len(marker_sample) - 1   # first pulse is initialization
            diff = 2 * len(exp_blocks) - n_logged
            print("  pulses logged (excluding initialization): %d, expected %d -> %s" % (
                n_logged, 2 * len(exp_blocks), "complete" if diff == 0 else ("%d missing" % diff if diff > 0 else "%d extra" % -diff)))
    else:
        print("  stimulus: none given (use --stimulus Protocol.py to store the definition)")
    print("Next: rgc-check-dataset %s" % out_path)


def pick_files():
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    raw = filedialog.askopenfilename(title="1/2  Choose the MaxLab raw recording (*.raw.h5)",
                                     filetypes=[("MaxLab raw", "*.raw.h5"), ("HDF5", "*.h5"), ("all", "*")])
    if not raw:
        sys.exit("cancelled")
    spk = filedialog.askopenfilename(title="2/2  Choose the SpyKING CIRCUS result (*.result-merged.hdf5)",
                                     initialdir=os.path.dirname(raw),
                                     filetypes=[("SpyKING CIRCUS result", "*.result-merged.hdf5"), ("HDF5", "*.hdf5 *.h5"),
                                                ("CSV", "*.csv"), ("all", "*")])
    if not spk:
        sys.exit("cancelled")
    stim = filedialog.askopenfilename(title="3/3  Choose the stimulus definition (*.py) -- Cancel to skip",
                                      filetypes=[("stimulus definition", "*.py"), ("all", "*")])
    return raw, spk, (stim or None)


def main():
    ap = argparse.ArgumentParser(prog="rgc-build-dataset", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raw", nargs="?", help="MaxLab raw recording, Trace_*.raw.h5")
    ap.add_argument("spikes", nargs="?", help="SpyKING CIRCUS Trace_*.result-merged.hdf5 (or a CSV with unit + spike_sample)")
    ap.add_argument("-o", "--out", help="output file (default: <raw name>.dataset.h5 next to the raw file)")
    ap.add_argument("--stimulus", help="stimulus definition file (visexpman/Linlab .py, e.g. protocols/Fullfield.py)")
    ap.add_argument("--rig", help="rig JSON (nominal frame rate, um/pixel, ...; see protocols/rig_example.json)")
    ap.add_argument("--gui", action="store_true", help="choose the input files with file dialogs")
    a = ap.parse_args()

    if a.gui or (a.raw is None and a.spikes is None):
        a.raw, a.spikes, stim = pick_files()
        a.stimulus = a.stimulus or stim
    if a.raw is None or a.spikes is None:
        ap.print_usage()
        fail("two input files are needed: the raw recording and the sorted spikes (or use --gui)")
    for p, what in [(a.raw, "raw recording"), (a.spikes, "spike file"), (a.stimulus, "stimulus file"), (a.rig, "rig file")]:
        if p and not os.path.isfile(p):
            fail("%s not found: %s" % (what, p))
    if not a.raw.endswith(".raw.h5"):
        print("WARNING: first argument does not end in .raw.h5 -- is it the MaxLab raw recording?")
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.raw)),
                                os.path.basename(a.raw).replace(".raw.h5", "") + ".dataset.h5")
    build(a.raw, a.spikes, out, a.stimulus, a.rig)


if __name__ == "__main__":
    main()

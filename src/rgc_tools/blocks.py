"""
Decode the logged stimulus pulses of a *.dataset.h5 into labelled blocks,
using the protocol stored in stimulus/protocol when available.

With a protocol: the expected sequence of marked blocks (frames at the nominal
rate) is walked against the logged pulses; the measured frame period converts
frames to samples. A missing pulse (interval ~ one block + one gap) is
re-inserted at its nominal position and flagged. Labels come from the protocol,
not from parity.

Without a protocol: falls back to rgc_tools.trials.decode_trials (two segment
lengths, alternate, even = onset) with label 'segment_A'.

Result: list of dicts (block_index, label, direction, repeat, start_sample,
end_sample, start_inferred, end_inferred) and a report list of strings.
"""
import datetime

import numpy as np

from .stimulus import read_protocol_group
from .trials import decode_trials

HEARTBEAT_VALUE = 160
TOL = 0.03      # relative tolerance on interval matching


def frame_period(bits_sample, bits_value, fs):
    hb = np.sort(bits_sample[bits_value == HEARTBEAT_VALUE])
    dt = np.diff(hb) / fs
    med = np.median(dt)
    return dt[(dt > 0.5 * med) & (dt < 1.5 * med)].mean() / 2


def decode_blocks(f):
    fs = float(f.attrs["sampling_rate_hz"])
    bits_s = f["stimulus/bits_raw/sample"][:]
    bits_v = f["stimulus/bits_raw/value"][:]
    mk = np.sort(f["stimulus/markers/sample"][:])
    report = []
    if len(mk) < 2:
        return [], ["fewer than 2 pulses; nothing to decode"]
    init = (mk[0] - bits_s[0]) / fs < 0.01
    pulses = mk[1:] if init else mk
    report.append("%d logged pulses%s" % (len(mk), ", first one at the log start dropped as initialization" if init else ""))
    proto = read_protocol_group(f)
    fp = frame_period(bits_s, bits_v, fs)

    if proto and proto["blocks"]:
        blocks = proto["blocks"]
        report.append("protocol %s: expecting %d blocks / %d pulses; measured frame period %.4f ms"
                      % (proto["class_name"], len(blocks), 2 * len(blocks), fp * 1e3))
        spf = fp * fs                                   # samples per frame
        out = []
        i = 0                                           # index into logged pulses
        t = int(pulses[0])                              # current pulse position
        inferred_here = False
        for b_idx, b in enumerate(blocks):
            start, start_inf = t, inferred_here
            exp_len = b["frames"] * spf
            # end pulse: next logged pulse should be ~exp_len later
            if i + 1 < len(pulses) and abs(pulses[i + 1] - start - exp_len) < TOL * exp_len:
                end, end_inf = int(pulses[i + 1]), False
                i += 1
            else:
                end, end_inf = int(round(start + exp_len)), True
                report.append("block %d (%s): end pulse missing, re-inserted at %.4f s" % (b_idx, b["label"], end / fs))
            out.append(dict(block_index=b_idx, label=b["label"], direction=b["direction"], repeat=b["repeat"],
                            start_sample=start, end_sample=end, start_inferred=start_inf, end_inferred=end_inf))
            # next block start: end + gap
            if b_idx + 1 < len(blocks):
                exp_gap = b["gap_frames"] * spf
                if i + 1 < len(pulses) and abs(pulses[i + 1] - end - exp_gap) < TOL * (exp_gap + exp_len):
                    t, inferred_here = int(pulses[i + 1]), False
                    i += 1
                else:
                    t, inferred_here = int(round(end + exp_gap)), True
                    report.append("block %d (%s): start pulse missing, re-inserted at %.4f s" % (b_idx + 1, blocks[b_idx + 1]["label"], t / fs))
        used = i + 1
        if used < len(pulses):
            report.append("WARNING: %d logged pulses left unassigned after the expected sequence (extra pulses?)" % (len(pulses) - used))
        n_inf = sum(o["start_inferred"] + o["end_inferred"] for o in out)
        report.append("decoded %d blocks; %d pulse(s) re-inserted" % (len(out), n_inf))
        return out, report

    # ---- fallback: no protocol ----
    on, off = decode_trials(mk, fs, bits_s[0])
    n = min(len(on), len(off))
    out = [dict(block_index=k, label="segment_A", direction=np.nan, repeat=k, start_sample=int(on[k]), end_sample=int(off[k]),
                start_inferred=False, end_inferred=False) for k in range(n)]
    report.append("no protocol stored: generic decoding (two alternating segment lengths, even-indexed pulses = onsets); "
                  "inferred pulses are not flagged in this mode")
    return out, report


def write_blocks(f, blocks, report):
    dt = np.dtype([("block_index", "<i4"), ("label", "S16"), ("direction", "<f8"), ("repeat", "<i4"),
                   ("start_sample", "<i8"), ("end_sample", "<i8"), ("start_inferred", "?"), ("end_inferred", "?")])
    arr = np.array([(b["block_index"], b["label"].encode(), b["direction"], b["repeat"], b["start_sample"], b["end_sample"],
                     b["start_inferred"], b["end_inferred"]) for b in blocks], dtype=dt)
    g = f["stimulus"]
    if "blocks" in g:
        del g["blocks"]
    d = g.create_dataset("blocks", data=arr)
    d.attrs["description"] = ("DECODED stimulus timeline (interpretation of stimulus/markers using stimulus/protocol): one row per "
                              "marked block, start/end in samples on the recording clock; *_inferred marks a pulse the logger "
                              "dropped, re-inserted at its nominal position")
    d.attrs["decoded"] = datetime.datetime.now().isoformat(timespec="seconds")
    d.attrs["decoding_report"] = "\n".join(report)
    return d


def load_blocks(f):
    """Blocks as a list of dicts from stimulus/blocks, or None if absent."""
    if "stimulus/blocks" not in f:
        return None
    arr = f["stimulus/blocks"][:]
    return [dict(block_index=int(a["block_index"]), label=a["label"].decode(), direction=float(a["direction"]),
                 repeat=int(a["repeat"]), start_sample=int(a["start_sample"]), end_sample=int(a["end_sample"]),
                 start_inferred=bool(a["start_inferred"]), end_inferred=bool(a["end_inferred"])) for a in arr]

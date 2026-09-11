"""
Stimulus protocol files (visexpman / Linlab) -> what the dataset needs to know.

A protocol file defines a Stimulus class whose `configuration()` sets parameters
(`self.NAME = value`) and whose `run()` calls block_start / block_end. Those two
calls are what pulse the digital marker line recorded in the raw file's
bits/0000 (value 0). Durations are executed as frame counts at the rig's
nominal frame rate (60 Hz), then played at the monitor's real refresh.

parse_protocol()   -> source text, hash, class name, parameters (via ast, no import)
expected_blocks()  -> for known classes, the sequence of marked blocks: label,
                      direction, repeat, marked duration (frames), unmarked gap
                      that follows (frames); and the marker semantics text.
"""
import ast
import hashlib
import json
import os

import numpy as np


def parse_protocol(path):
    src = open(path).read()
    tree = ast.parse(src)
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef)), None)
    if cls is None:
        raise ValueError("no class definition in %s" % path)
    params = {}
    conf = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "configuration"), None)
    if conf is None:
        raise ValueError("class %s has no configuration() method" % cls.name)
    for node in ast.walk(conf):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                try:
                    params[t.attr] = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    params[t.attr] = ast.get_source_segment(src, node.value) if hasattr(ast, "get_source_segment") else "<expr>"
    return dict(source=src, sha1=hashlib.sha1(src.encode()).hexdigest(), class_name=cls.name,
                file_name=os.path.basename(path), parameters=params)


def expected_blocks(proto, fps=60.0):
    """Return (blocks, semantics). blocks: list of dicts with label, direction, repeat,
    frames (marked duration), gap_frames (unmarked interval to the next block's start).
    Unknown classes return ([], generic text)."""
    p, name = proto["parameters"], proto["class_name"]
    fr = lambda sec: int(round(float(sec) * fps))
    if name == "Fullfield":
        on, off = fr(p["ONTIME"]), fr(p["OFFTIME"])
        blocks = [dict(label="on", direction=np.nan, repeat=r, frames=on, gap_frames=off) for r in range(int(p["REPEATS"]))]
        sem = ("bits==0 pulses come from block_start/block_end around show_shape: one pulse at light ON, one at light OFF. "
               "The %.1f s background (OFFTIME) and the %.1f s WAIT at start and end are unmarked. "
               "Durations are frame counts at the nominal frame rate (%d ON + %d OFF frames)." % (p["OFFTIME"], p["WAIT"], on, off))
        first_marked_after_start_frames = fr(p["WAIT"])
    elif name == "MovingGrating":
        sweep, stand = fr(p["SWEEP_TIME"]), fr(p["STAND_TIME"])
        blocks = [dict(label="sweep", direction=float(d), repeat=r, frames=sweep, gap_frames=stand)
                  for r in range(int(p["REPETITIONS"])) for d in p["DIRECTIONS"]]
        sem = ("bits==0 pulses come from block_start(('sweep', d))/block_end around the moving grating: one pulse at sweep "
               "onset, one at sweep end. The %.1f s static grating (STAND_TIME) shown before each sweep, and the %.1f s WAIT "
               "at start and end, are unmarked; the interval between one sweep's end and the next sweep's start is the "
               "static grating of the next direction (%d frames). Direction of block k = DIRECTIONS[k %% %d], repeat = k // %d."
               % (p["STAND_TIME"], p["WAIT"], stand, len(p["DIRECTIONS"]), len(p["DIRECTIONS"])))
        first_marked_after_start_frames = fr(p["WAIT"]) + stand
    else:
        return [], ("class %s: marker semantics not known to rgc_tools; bits==0 pulses correspond to block_start/block_end "
                    "calls in run()" % name), None
    return blocks, sem, first_marked_after_start_frames


def write_protocol_group(f, proto, rig, fps):
    """Write stimulus/protocol into an open h5py file."""
    g = f.require_group("stimulus").require_group("protocol")
    blocks, sem, first_after = expected_blocks(proto, fps)
    g.attrs["program"] = rig.get("stimulus_program", "visexpman (Linlab)") if rig else "visexpman (Linlab)"
    g.attrs["class_name"] = proto["class_name"]
    g.attrs["source_file"] = proto["file_name"]
    g.attrs["source_sha1"] = proto["sha1"]
    g.attrs["nominal_frame_rate_hz"] = fps
    g.attrs["marker_semantics"] = sem
    g.attrs["parameters_json"] = json.dumps(proto["parameters"])
    for k, v in proto["parameters"].items():
        try:
            g.attrs["param_" + k] = v
        except TypeError:
            g.attrs["param_" + k] = json.dumps(v)
    if "source_code" in g:
        del g["source_code"]
    g.create_dataset("source_code", data=np.array(proto["source"].encode()))
    g["source_code"].attrs["description"] = "verbatim stimulus definition file; decode with .tobytes().decode()"
    if blocks:
        g.attrs["expected_n_blocks"] = len(blocks)
        g.attrs["expected_n_pulses"] = 2 * len(blocks)
        g.attrs["first_pulse_after_stimulus_start_frames"] = first_after
        dt = np.dtype([("label", "S16"), ("direction", "<f8"), ("repeat", "<i4"), ("frames", "<i4"), ("gap_frames", "<i4")])
        arr = np.array([(b["label"].encode(), b["direction"], b["repeat"], b["frames"], b["gap_frames"]) for b in blocks], dtype=dt)
        if "expected_blocks" in g:
            del g["expected_blocks"]
        g.create_dataset("expected_blocks", data=arr)
        g["expected_blocks"].attrs["description"] = ("blocks in presentation order as defined by the protocol: marked duration "
                                                     "(frames at nominal rate) and the unmarked gap that follows, until the next block")
    if rig:
        r = g.require_group("rig")
        for k, v in rig.items():
            if v is None:
                continue
            try:
                r.attrs[k] = v
            except TypeError:
                r.attrs[k] = json.dumps(v)
    return blocks


def read_protocol_group(f):
    """Return dict with expected blocks etc. from an open dataset file, or None."""
    if "stimulus/protocol" not in f:
        return None
    g = f["stimulus/protocol"]
    out = dict(g.attrs)
    if "expected_blocks" in g:
        eb = g["expected_blocks"][:]
        out["blocks"] = [dict(label=b["label"].decode(), direction=float(b["direction"]), repeat=int(b["repeat"]),
                              frames=int(b["frames"]), gap_frames=int(b["gap_frames"])) for b in eb]
    else:
        out["blocks"] = []
    return out

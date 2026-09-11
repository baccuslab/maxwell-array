# rgc_tools

Three commands for MaxLab (MaxWell) retina recordings sorted with SpyKING CIRCUS
and stimulated with visexpman / Linlab:

| command | what it does |
|---|---|
| `rgc-build-dataset` | combines a raw recording (`Trace_*.raw.h5`), its sorted spikes (`Trace_*.result-merged.hdf5`) and the stimulus definition (`Fullfield.py`, `MovingGrating.py`, ...) into one small `*.dataset.h5` file |
| `rgc-check-dataset` | checks that file: do the spikes belong to that recording, what did the stimulus marker line record, was any pulse dropped, does it match the protocol; `--write-blocks` stores the decoded, labelled stimulus timeline |
| `rgc-raster` | raster + PSTH for one unit, aligned to the stimulus blocks |

The dataset file is ~5 MB (the raw file is ~500 MB) and contains everything needed
for analysis except the voltage traces. It does **not** need MaxWell's HDF5
compression plugin, because the tools never read the traces.

## Install (once)

With conda (recommended):

```
conda env create -f environment.yml
conda activate rgc
```

Or with plain Python (3.7 or newer):

```
pip install .
```

Check: `rgc-build-dataset --help`

## Use

```
rgc-build-dataset  Trace_X.raw.h5  Trace_X.result-merged.hdf5  --stimulus protocols/Fullfield.py
rgc-check-dataset  Trace_X.dataset.h5  --write-blocks
rgc-raster         Trace_X.dataset.h5  temp_2
rgc-raster         Trace_X.dataset.h5  temp_76  --direction 90        # grating: one direction
```

`--stimulus` takes the stimulus definition file that was run (the visexpman
class with `configuration()` and `run()`); copies of the lab's protocols are in
`protocols/`. `--rig protocols/rig_example.json` adds rig values the definition
does not contain (nominal frame rate, µm per pixel). Without `--stimulus` the
dataset is still built, but blocks cannot be labelled.

If you would rather not type file paths, run `rgc-build-dataset --gui` (or just
`rgc-build-dataset` with no arguments) and pick the files in dialogs;
`rgc-check-dataset --gui` likewise.

`rgc-check-dataset` ends with a one-line VERDICT, e.g.

```
VERDICT: spikes belong to this raw file; 50 stimulus pulses = 25 trials of 120.0 + 150.0 frames;
1 dropped pulse(s); protocol Fullfield: 25 blocks decoded, 1 pulse(s) re-inserted; stimulus/blocks written
```

If it says `DO NOT belong to`, the spike file was sorted from a different recording.

## What is in a dataset file

Every time in the file is a **sample index** on the recording's 20 kHz clock
(`sample = frame number − first frame number`), so spikes and stimulus markers
are directly comparable.

| path | contents | kind |
|---|---|---|
| root attributes | source file names (raw, spikes, stimulus, rig), sampling rate, first frame number, number of samples/channels, recording start/stop, chip type/id, gain, filter, threshold | record |
| `stimulus/bits_raw/{sample,time_sec,value}` | every row of the raw file's digital-input log (`bits/0000`) | record |
| `stimulus/markers/{sample,time_sec}` | the rows with value 0 — the stimulus program's pulses, exactly as logged | record |
| `stimulus/protocol` | the stimulus definition: verbatim source (`source_code`), parsed parameters (`param_*` attrs, `parameters_json`), `marker_semantics`, `expected_blocks` (label, direction, repeat, frames, gap_frames), `nominal_frame_rate_hz`; `rig/` attrs if given | record (of the program) |
| `stimulus/blocks` | **decoded** timeline written by `rgc-check-dataset --write-blocks`: one row per marked block with label, direction, repeat, start/end sample, and `*_inferred` flags for pulses the logger dropped | interpretation |
| `raw_threshold_crossings` | the recording's online spike detections (sample, channel, amplitude) | record |
| `electrode_mapping` | channel → electrode id, x, y (µm) | record |
| `spikes/<unit>/{spike_sample,spike_time_sec,amplitude}` | sorted spikes per unit | record |

## How the stimulus is marked

visexpman pulses the marker line at every `block_start` / `block_end` call in the
protocol's `run()`:

* **Fullfield**: pulse at light ON and at light OFF (the `on` block); the 2.5 s
  background and the 0.5 s WAIT at start and end are unmarked. 25 blocks → 50 pulses.
* **MovingGrating**: pulse at sweep onset and sweep end (the `('sweep', d)` block);
  the 1 s static grating shown before each sweep is unmarked, so the interval
  between one sweep's end and the next sweep's start is the static grating of the
  next direction. 8 directions × 2 repeats = 16 blocks → 32 pulses; direction of
  block k = `DIRECTIONS[k mod 8]`.

Durations are executed as **frame counts at the nominal 60 Hz** (2.0 s → 120 frames)
but the monitor actually refreshes at ~61.3 Hz (measured from the heartbeat), so a
nominal 4.5 s flash cycle lasts 4.40 s. Always take timing from the markers/blocks,
not from the nominal durations.

Two quirks the tools handle: the first logged pulse coincides with the start of the
log and is an initialization value; occasionally the logger drops one pulse (visible
as an interval equal to block + gap), which `rgc-check-dataset` re-inserts at its
nominal position and flags.

## Reading a dataset file yourself

```python
import h5py, numpy as np
f = h5py.File("Trace_..._full.dataset.h5", "r")
fs     = f.attrs["sampling_rate_hz"]
blocks = f["stimulus/blocks"][:]                      # label, direction, start_sample, end_sample, ...
on     = blocks["start_sample"]                        # light ON (Fullfield) / sweep onset (MovingGrating)
spikes = f["spikes/temp_2/spike_sample"][:]
t_rel  = (spikes[:, None] - on[None, :]) / fs          # seconds from every block start
src    = f["stimulus/protocol/source_code"][()].tobytes().decode()   # the protocol that ran
```

## Files these tools expect

* `Trace_<date>_<sample>-<eye>-<region>-<n>-<stimulus>.raw.h5` — MaxLab Live recording
* `Trace_<...>.result-merged.hdf5` — SpyKING CIRCUS output for that recording
  (a CSV with columns `unit`, `spike_sample` is also accepted)
* the visexpman stimulus `.py` that was run (see `protocols/`)

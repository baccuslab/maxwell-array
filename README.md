# rgc_tools

Tools for retinal recordings made with a MaxWell (MaxLab Live) multielectrode array,
spike-sorted with SpyKING CIRCUS, and stimulated with visexpman / Linlab. Three commands:

| command | what it does |
|---|---|
| `rgc-build-dataset` | combines a raw recording (`*.raw.h5`), its sorted spikes (`*.result-merged.hdf5`) and the stimulus definition (`*.py`) into one small `*.dataset.h5` file |
| `rgc-check-dataset` | checks that file: do the spikes belong to that recording, what did the stimulus marker line record, was any pulse dropped, does the record match the stimulus definition; `--write-blocks` stores the decoded, labelled stimulus timeline |
| `rgc-raster` | raster + PSTH for one unit, aligned to the stimulus blocks |

The dataset file contains

1. stimulus timing and other information from the raw recording `.h5` file,
2. sorted spikes from SpyKING CIRCUS,
3. the stimulus definition that was run (the visexpman protocol file, verbatim and parsed).

It is ~1% of the size of the raw file and contains everything needed for analysis
except the voltage traces, which the tools never read (so MaxWell's HDF5 compression
plugin is not required).

## Install (once)

(Python 3.7 or newer with pip):

```
pip install git+https://github.com/baccuslab/maxwell-array
```

This downloads the package, installs numpy/h5py/matplotlib if they are missing, and
puts the three commands on your path. To keep the tools separate from other Python
software, you can first create and activate a virtual environment:

```
python3 -m venv ~/rgc-env
source ~/rgc-env/bin/activate        # Windows: rgc-env\Scripts\activate
pip install git+https://github.com/baccuslab/maxwell-array
```

(then `source ~/rgc-env/bin/activate` again in each new terminal before using the commands).


The three commands `rgc-build-dataset`, `rgc-check-dataset`, `rgc-raster`
are then available in the terminal. Check with `rgc-build-dataset --help`.

To update to a newer version later: repeat the same `pip install` line (add `--upgrade`
for Option A), or `git pull` then `pip install .` for Option B.

## Use

```
rgc-build-dataset  <recording>.raw.h5  <recording>.result-merged.hdf5  --stimulus <Protocol>.py
rgc-check-dataset  <recording>.dataset.h5  --write-blocks
rgc-raster         <recording>.dataset.h5  <unit>
```

`--stimulus` takes the visexpman stimulus file that was run for that recording (the
class with `configuration()` and `run()`). Copies of the lab's protocols are kept in
`protocols/`; use the one that matches the recording. `--rig <rig>.json` adds rig
values the stimulus file does not contain (nominal frame rate, µm per pixel; see
`protocols/rig_example.json`). Without `--stimulus` the dataset is still built, but
the stimulus blocks cannot be labelled.

`rgc-raster` options: `--tmax` and `--bin` for the PSTH window and bin, `--direction`
to select blocks of one direction in protocols that have directions, `auto` (default)
for the unit to pick the most strongly modulated one.

If you would rather not type file paths, run `rgc-build-dataset --gui` (or just
`rgc-build-dataset` with no arguments) and pick the files in dialogs;
`rgc-check-dataset --gui` likewise.

`rgc-check-dataset` ends with a one-line VERDICT. For example, for a full-field
flash recording:

```
VERDICT: spikes belong to this raw file; 50 stimulus pulses = 25 trials of 120.0 + 150.0 frames;
1 dropped pulse(s); protocol Fullfield: 25 blocks decoded, 1 pulse(s) re-inserted; stimulus/blocks written
```

If it says `DO NOT belong to`, the spike file was sorted from a different recording.

## What is in a dataset file

Every time in the file is a **sample index** on the recording's clock (20 kHz on the
MaxOne; `sample = frame number − first frame number`), so spikes and stimulus markers
are directly comparable without any unit conversion.

| path | contents | kind |
|---|---|---|
| root attributes | source file names (raw, spikes, stimulus, rig), sampling rate, first frame number, number of samples/channels, recording start/stop, chip type/id, gain, filter, threshold | record |
| `stimulus/bits_raw/{sample,time_sec,value}` | every row of the raw file's digital-input log (`bits/0000`) | record |
| `stimulus/markers/{sample,time_sec}` | the rows with value 0 — the stimulus program's pulses, exactly as logged | record |
| `stimulus/protocol` | the stimulus definition: verbatim source (`source_code`), parsed parameters (`param_*` attrs, `parameters_json`), `marker_semantics`, `expected_blocks`, `nominal_frame_rate_hz`; `rig/` attrs if given | record (of the program) |
| `stimulus/blocks` | **decoded** timeline written by `rgc-check-dataset --write-blocks`: one row per marked block with label, direction, repeat, start/end sample, and `*_inferred` flags for pulses the logger dropped | interpretation |
| `raw_threshold_crossings` | the recording's online spike detections (sample, channel, amplitude) | record |
| `electrode_mapping` | channel → electrode id, x, y (µm) | record |
| `spikes/<unit>/{spike_sample,spike_time_sec,amplitude}` | sorted spikes per unit | record |

Everything marked *record* is copied from the source files without interpretation.
`stimulus/blocks` is the one derived table, kept separate so that the raw record and
its interpretation can never be confused.

## How stimulus timing is recorded

The raw file's `bits/0000` log has two kinds of rows. Values 128/160 alternate as a
per-frame heartbeat from the display (one row every two frames), from which the true
monitor refresh rate is measured. Value 0 is a pulse that visexpman emits at every
`block_start` / `block_end` call in the protocol's `run()`. What a pulse *means*
therefore depends on the protocol — which is why the stimulus file is stored in the
dataset and used to label the pulses:

* **Fullfield** (example): `block_start`/`block_end` bracket the light step, so
  pulses mark light ON and light OFF; the background period and the WAIT at start and
  end are unmarked.
* **MovingGrating** (example): the block brackets the moving grating, so pulses mark
  sweep onset and sweep end; the static grating shown before each sweep is unmarked,
  and the direction of each block follows the protocol's `DIRECTIONS` list.
* **Other protocols**: the definition is always stored verbatim with its parameters.
  If the class is not yet known to `rgc_tools`, pulses are decoded generically (two
  alternating interval lengths, even-indexed pulses taken as onsets) and the blocks are
  labelled `segment_A`. To add a protocol, add a branch to `expected_blocks()` in
  `src/rgc_tools/stimulus.py` that lists its marked blocks (label, direction, repeat,
  duration in frames, and the unmarked gap that follows) from the parsed parameters.

Two general facts about these recordings:

* Durations in a protocol are executed as **frame counts at the nominal frame rate**
  (60 Hz), but the monitor refreshes at whatever rate it actually runs (~61.3 Hz on the
  lab's rig, measured from the heartbeat). Nominal durations are therefore about 2%
  long, and the error accumulates over a recording. Take timing from the markers /
  blocks, never from the nominal durations or from a fixed assumed period.
* The logger has two quirks the tools handle: the first logged pulse coincides with the
  start of the log and is an initialization value, not a stimulus event; and the logger
  occasionally drops one pulse (visible as an interval equal to block + gap), which
  `rgc-check-dataset` re-inserts at its nominal position and flags in `stimulus/blocks`.

## Reading a dataset file yourself

```python
import h5py, numpy as np
f = h5py.File("<recording>.dataset.h5", "r")
fs     = f.attrs["sampling_rate_hz"]
blocks = f["stimulus/blocks"][:]                      # label, direction, repeat, start_sample, end_sample, ...
starts = blocks["start_sample"]                        # marked-block onsets (e.g. light ON, sweep onset)
spikes = f["spikes/<unit>/spike_sample"][:]
t_rel  = (spikes[:, None] - starts[None, :]) / fs      # seconds from every block start
src    = f["stimulus/protocol/source_code"][()].tobytes().decode()   # the protocol that ran
```

## Files these tools expect

* `<recording>.raw.h5` — MaxLab Live recording (e.g. `Trace_<date>_<sample>-<eye>-<region>-<n>-<stimulus>.raw.h5`)
* `<recording>.result-merged.hdf5` — SpyKING CIRCUS output for that recording
  (a CSV with columns `unit`, `spike_sample` is also accepted)
* the visexpman stimulus `.py` that was run (see `protocols/`)
* optionally a rig `.json` (see `protocols/rig_example.json`)

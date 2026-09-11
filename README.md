# maxwell-array tools

Turns a MaxWell (MaxLab Live) retina recording, its SpyKING CIRCUS sorted spikes, and the
stimulus definition into **one small file** (`Trace_...dataset.h5`) that holds the spikes
and the exact stimulus timing, ready for analysis.

Everything below is typed into the **Terminal** app (Applications → Utilities → Terminal).
Copy each line exactly, press Return, and wait for it to finish before typing the next one.

## Part 1 — Install (do this once per computer)

```
python3 -m venv ~/rgc-env
~/rgc-env/bin/pip install git+https://github.com/baccuslab/maxwell-array
```

To check installation:

```
~/rgc-env/bin/rgc-build-dataset --help
```

You should see text starting with `usage: rgc-build-dataset`. Installation is finished.
You do not need to repeat Part 1 on this computer (unless asked to update — see the end).

## Part 2 — Make a dataset file (do this for every recording)

You need three files for the recording:

| file | comes from |
|---|---|
| `Trace_...raw.h5` | MaxLab Live (the recording) |
| `Trace_...result-merged.hdf5` | SpyKING CIRCUS (the sorted spikes) |
| the stimulus file, e.g. `Fullfield.py` or `MovingGrating.py` | the stimulus program — the one that was run for this recording |

**Step 1 — build the dataset file:**

```
~/rgc-env/bin/rgc-build-dataset --gui
```

Three file-chooser windows open one after another: pick the raw `.h5`, then the
`.result-merged.hdf5`, then the stimulus `.py`. The program prints a few lines and writes
`Trace_...dataset.h5` in the same folder as the raw file.

**Step 2 — check it and label the stimulus:**

```
~/rgc-env/bin/rgc-check-dataset --gui --write-blocks
```

Pick the `.dataset.h5` file you just made. The program prints a report whose last line
starts with `VERDICT:`. Read it:

* `spikes belong to this raw file` — good.
* `spikes DO NOT belong to this raw file` — the sorted-spike file is from a different
  recording; check that you picked matching files.
* `... 1 dropped pulse(s) ...` — normal; the program has repaired it.
* `stimulus/blocks written` — good; the dataset file is complete.

That's it. The `.dataset.h5` file is what you keep and analyse; the raw file is no longer
needed for spike or stimulus-timing analysis.

**Optional — look at one cell:**

```
~/rgc-env/bin/rgc-raster --help
```

shows how; for example
`~/rgc-env/bin/rgc-raster /path/to/Trace_...dataset.h5 temp_2` saves a raster/PSTH image
next to the dataset file.

## Coming back after a break

Nothing to reinstall and nothing to "activate". Open Terminal and go straight to Part 2.
If you are unsure whether the install is still there, run the check line from Part 1.

## If something goes wrong

| what you see | what it means / what to do |
|---|---|
| `command not found` | Part 1 was not done on this computer, or the line was mistyped. Run the two lines of Part 1 again (repeating them is harmless). |
| `Permission denied ... site-packages` | `pip install` was run without `~/rgc-env/bin/` in front. Use the exact lines above. |
| `python3: command not found` | Python is not installed. Install it from python.org (3.7 or newer), then start Part 1 again. |
| `ERROR: ... needs a 'spike_sample' column` | You picked a CSV that is not a spike file. Pick the `.result-merged.hdf5`. |
| `does not look like a MaxLab raw file` | The first file you picked is not the `.raw.h5`. |
| `spikes DO NOT belong to this raw file` | The raw file and the spike file are from different recordings. |
| No file-chooser window appears | It may be behind other windows; look in the Dock for a Python icon. |
| Anything else | Select all the text in the Terminal window, copy it, and send it together with the names of the three files you used. |

## Updating to a newer version (only when asked to)

```
~/rgc-env/bin/pip install --upgrade git+https://github.com/baccuslab/maxwell-array
```

## What is inside the dataset file

`Trace_...dataset.h5` is an HDF5 file. It can be opened with any HDF5 reader (Python
`h5py`, MATLAB `h5read`/`h5readatt`, HDFView). Times are stored as **sample numbers** on
the recording's clock: `time in seconds = sample / sampling_rate_hz` (20 000 Hz on the
MaxOne). Sample 0 is the first sample of the raw recording. Spike times and stimulus
times use the same clock, so they can be compared directly.

### Root attributes (properties of the whole file)

| attribute | meaning |
|---|---|
| `source_raw_file`, `source_raw_path` | name and full path of the MaxLab `.raw.h5` the file was built from |
| `source_spike_file`, `source_spike_path`, `source_spike_format` | the SpyKING CIRCUS (or CSV) spike file and how it was read |
| `source_stimulus_file`, `source_rig_file` | the stimulus definition `.py` and rig `.json` given at build time (empty if none) |
| `created`, `created_by` | when the file was made and by which command |
| `sampling_rate_hz` | samples per second of the recording (20000) |
| `first_frame_no` | MaxLab frame number of sample 0 (`sample = frame number − first_frame_no`) |
| `n_samples`, `n_channels`, `duration_sec` | length of the recording in samples and seconds; number of recorded channels |
| `frame_nos_contiguous` | `True` if no samples were dropped in the recording |
| `recording_start_ms`, `recording_stop_ms` | wall-clock start and stop, milliseconds since 1970 (Unix time) |
| `lsb_volts`, `gain`, `hpf_hz`, `spike_threshold` | MaxLab acquisition settings: volts per ADC step, amplifier gain, high-pass filter (Hz), online spike-detection threshold (× noise) |
| `chip_type`, `chip_id`, `well_name`, `plating_date`, `maxlab_version`, `file_format_version` | chip and software identification copied from the raw file |
| `sample_convention` | one sentence stating the sample/time convention above |
| `empty_groups_in_raw` | groups of the raw file that were empty (for the record) |

### `stimulus/bits_raw` — the digital-input log, as recorded

| dataset | meaning |
|---|---|
| `sample` | sample number of each transition of the digital input lines |
| `time_sec` | the same, in seconds |
| `value` | the digital value after the transition. `128` and `160` alternate as the display's frame heartbeat (one row every 2 frames); `0` is a stimulus pulse |

### `stimulus/markers` — the stimulus pulses, as recorded

| item | meaning |
|---|---|
| `sample`, `time_sec` | the rows of `bits_raw` with value 0, i.e. every pulse the stimulus program sent (it sends one at each `block_start` and `block_end`). Nothing is added or removed here: the first pulse is the program's initialization pulse, and a pulse the logger dropped is simply absent |
| attribute `n_markers` | number of pulses |

### `stimulus/protocol` — the stimulus definition that was run

| item | meaning |
|---|---|
| `source_code` (dataset) | the stimulus `.py` file, verbatim (decode with `.tobytes().decode()` in Python) |
| `class_name`, `source_file`, `source_sha1`, `program` | stimulus class (e.g. `Fullfield`), file name, checksum of the file, stimulus program (visexpman / Linlab) |
| `param_<NAME>` | one attribute per parameter set in the class's `configuration()`, e.g. `param_ONTIME`, `param_REPEATS`, `param_DIRECTIONS`, with the value from the file |
| `parameters_json` | the same parameters as one JSON string |
| `nominal_frame_rate_hz` | the frame rate the stimulus program assumes (60). Durations in the protocol are executed as frame counts at this rate, while the monitor's real rate is measured from the heartbeat |
| `marker_semantics` | a sentence stating what the pulses mean for this protocol (e.g. light ON / light OFF; sweep onset / sweep end) |
| `expected_n_blocks`, `expected_n_pulses` | how many marked blocks and pulses the protocol should produce |
| `first_pulse_after_stimulus_start_frames` | nominal frames from the start of the stimulus program to the first pulse |
| `expected_blocks` (dataset) | one row per block in presentation order: `label`, `direction` (degrees; NaN if the protocol has none), `repeat`, `frames` (marked duration), `gap_frames` (unmarked interval until the next block), all in frames at the nominal rate |
| `rig/` (group) | attributes copied from the rig `.json`, if one was given (rig name, nominal frame rate, µm per pixel, ...) |

### `stimulus/blocks` — the decoded stimulus timeline (written by `rgc-check-dataset --write-blocks`)

This is the table to use for analysis. One row per marked block:

| field | meaning |
|---|---|
| `block_index` | 0, 1, 2, ... in presentation order |
| `label` | block type from the protocol, e.g. `on` (Fullfield), `sweep` (MovingGrating) |
| `direction` | direction in degrees for protocols that have one, otherwise NaN |
| `repeat` | which repetition of the protocol's sequence this block belongs to |
| `start_sample`, `end_sample` | when the block started and ended (sample numbers; divide by `sampling_rate_hz` for seconds). For Fullfield: light ON and light OFF. For MovingGrating: sweep onset and sweep end |
| `start_inferred`, `end_inferred` | `True` if that pulse was missing from the log and was re-inserted at its nominal position |
| attributes `decoded`, `decoding_report`, `description` | when the decoding was done, the report printed by the checker, and a description |

### `raw_threshold_crossings` — MaxLab's online spike detections

One row per event detected by the recording software (all channels, unsorted):
`sample`, `channel` (recording channel), `amplitude`. Used by the checker to verify that
the sorted spikes belong to this recording; also usable as a population-level signal.

### `electrode_mapping` — where each channel is

One row per recorded channel: `channel` (recording channel number), `electrode`
(electrode id on the chip), `x`, `y` (position on the array, µm).

### `spikes` — the sorted spikes

| item | meaning |
|---|---|
| attributes `n_units`, `unit_names` | number of units and their names, e.g. `temp_0`, `temp_1`, ... (SpyKING CIRCUS template names) |
| `spikes/<unit>/spike_sample` | spike times of that unit, sample numbers |
| `spikes/<unit>/spike_time_sec` | the same, in seconds |
| `spikes/<unit>/amplitude` | SpyKING CIRCUS amplitude per spike: two columns, the template amplitude and the amplitude of the template's derivative component |
| attribute `n_spikes` (per unit) | number of spikes |

### Reading it in Python

```python
import h5py
f = h5py.File("Trace_...dataset.h5", "r")
fs     = f.attrs["sampling_rate_hz"]
blocks = f["stimulus/blocks"][:]
on     = blocks["start_sample"] / fs                  # block onsets in seconds
spikes = f["spikes/temp_2/spike_sample"][:] / fs      # one unit's spike times in seconds
```

---


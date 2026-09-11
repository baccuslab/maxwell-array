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

---

*Want to know what is inside the dataset file, how stimulus timing is recorded, or how to
add a new stimulus protocol? See [REFERENCE.md](REFERENCE.md).*

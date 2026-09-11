"""
Derive trial structure from the logged stimulus markers in a *.dataset.h5 file.

The dataset file stores the markers uninterpreted. The rules applied here:
  - the first marker, if it coincides with the start of the bits log, is an
    initialization value and is dropped;
  - marker intervals cluster into two segment lengths; an interval equal to
    their sum is a dropped pulse, and a marker is re-inserted there;
  - markers then alternate; even-indexed ones are taken as segment-A onsets.
Run `rgc-check-dataset` to confirm these assumptions hold for a new file.
"""
import numpy as np


def decode_trials(markers, fs, log_start):
    """Return (onsets, offsets) in samples. onsets[i] starts trial i."""
    m = np.sort(np.asarray(markers, dtype=np.int64))
    if len(m) < 3:
        raise ValueError("fewer than 3 stimulus markers; cannot derive trials")
    if (m[0] - log_start) / fs < 0.01:
        m = m[1:]
    g = np.diff(m)
    if np.ptp(g) > 0.1 * np.median(g):
        split = (g.min() + np.median(g)) / 2
        short = np.median(g[g < split])
        long_ = np.median(g[(g >= split) & (g < 1.5 * np.median(g[g >= split]))])
        pair = short + long_
        for _ in range(10):
            g = np.diff(m)
            bad = np.where(np.abs(g - pair) < 0.03 * pair)[0]
            if len(bad) == 0:
                break
            i = bad[0]
            ref = g[i - 1] if i > 0 else g[i + 1]
            ref_is_short = abs(ref - short) < abs(ref - long_)
            seg = (long_ if ref_is_short else short) if i > 0 else (short if ref_is_short else long_)
            m = np.insert(m, i + 1, m[i] + int(round(seg)))
    return m[::2], m[1::2]


def align(spike_samples, onsets, period):
    """Assign spikes to trials. Returns (trial_index, sample_within_trial)."""
    rel = spike_samples[:, None] - onsets[None, :]
    inside = (rel >= 0) & (rel < period)
    ok = inside.any(axis=1)
    trial = np.argmax(inside, axis=1)
    return trial[ok], rel[ok, trial[ok]]

---
type: Pipeline Stage
title: Segment selection (audio energy)
description: Picks the liveliest target-duration window of a clip by sliding a window over per-0.5s audio RMS; also supplies energy curves and candidate windows to the compilation edit.
tags: [pipeline, audio, energy, segmentation]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/segment.py
---

# Segment selection (audio energy)

`backend/pipeline/segment.py` — rationale: in trip footage the loud moments (waves, crowds, engines, laughter) are usually the interesting ones.

## Functions

- `energy_curve(path, info)` — decodes audio once to 16 kHz mono s16 PCM via ffmpeg, returns RMS per 0.5 s window (`np.ndarray`), or `None` when there's no audio / decode fails / under 1 s of samples.
- `candidate_windows(rms, window_s, k)` — top-k *non-overlapping* windows of the given length as `[(start_seconds, mean_rms_score)]`, best first, computed with a cumulative-sum sliding mean. If the window doesn't fit, returns the whole clip as one candidate.
- `select_segment(path, info, target, strategy)` — returns `(start, duration)`:
  - Clip ≤ target+0.5 s → whole clip.
  - Strategy `first`, no audio, or energy analysis fails → `(0, target)`.
  - Strategy `energy` → best candidate window, clamped so it fits inside the clip.

## Consumers

- [Single-clip pipeline](single-clip.md) calls `select_segment` (config: `video.segment_strategy`, `video.target_duration`).
- [Compilation pipeline](compilation.md) uses `energy_curve` + `candidate_windows(k=3)` per clip: the curve becomes prompt evidence for [edit-ai](edit-ai.md), and the windows serve as both prompt hints and the deterministic fallback edit's placements.

---
type: Pipeline
title: Single-clip pipeline
description: Turns one raw clip into a finished ~25s vertical Short in one ffmpeg pass, with stages probe → select → transcribe → analyze → render → write outputs.
tags: [pipeline, video, orchestration]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/runner.py
---

# Single-clip pipeline

`process_video(src, cfg, on_stage, on_progress)` in `backend/pipeline/runner.py` orchestrates every stage in order and returns a result dict. Used by both the web worker ([Job queue](../architecture/job-queue.md)) and the CLI harness (`backend/scripts/process_one.py`).

## Stages (in order, with the `stage` labels the UI shows)

1. **probing** — [probe](probe.md): duration, display dimensions, fps, audio presence, HDR flag, GPS, creation time.
2. **selecting** — [segment](segment.md): pick the `(start, duration)` window (`energy` or `first` strategy, target `video.target_duration`).
3. **transcribing** *(only if `captions.enabled` and the clip has audio)* — extract the selected window to 16 kHz mono WAV via ffmpeg, then [transcribe](transcribe.md). May return `None` (no usable speech) → captions skipped.
4. **analyzing** — [frames](frames.md) extracts 3 JPEGs at 15/50/85% of the window; [metadata-ai](metadata-ai.md) produces titles/hashtags/hook/location (Claude vision or offline fallback).
5. Overlay prep — [captions](captions.md) rasterizes the hook (if enabled and non-empty) and each transcript segment to transparent PNGs.
6. **rendering** — [render](render.md): `pick_music` chooses a random track (unless `music_mode: none`), `build_command` assembles the single-pass ffmpeg graph, `run_render` executes it and reports percent progress.
7. **writing_outputs** — copies the middle extracted frame as `thumbnail.jpg`, writes `_metadata.json` and human-readable `_metadata.txt`, deletes the `work/` dir.

## Outputs

Everything lands in `output/<safe_stem>/`: `<stem>_short.mp4`, `thumbnail.jpg`, `<stem>_metadata.json`, `<stem>_metadata.txt`. The result dict includes `titles`, `hashtags`, `hook`, `location_guess`, `transcript`, `metadata_fallback`, `music`, `segment {start, duration}`, and `source` info. Filenames are sanitized to `[A-Za-z0-9_-]`.

## Design invariant

AI stages never block a render: [metadata-ai](metadata-ai.md) falls back to offline templates on any failure, and captions/music degrade to "off" — the only hard failures are unreadable input, no extractable frames, or an ffmpeg render error.

## Related

- [Compilation pipeline](compilation.md) — the multi-clip counterpart
- [Configuration](../config/settings.md) — every knob these stages read

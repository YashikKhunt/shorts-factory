---
type: Pipeline
title: Compilation pipeline
description: Cuts 2–8 clips into one Short — per-clip evidence gathering, an AI (or fallback) edit decision list, per-clip mezzanine normalization, concat, and a final render.
tags: [pipeline, compilation, multi-clip, orchestration]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/compilation.py
---

# Compilation pipeline

`process_compilation(srcs, cfg, on_stage, on_progress, name)` in `backend/pipeline/compilation.py` cuts several clips into ONE Short. Triggered by uploading ≥2 files with the "combine" toggle (max `compilation.max_clips`, default 8).

## Flow

1. **probing** — [probe](probe.md) each clip. If *every* clip has a parseable `creation_time`, clips are re-ordered chronologically; otherwise selection order is kept.
2. **analyzing_clips** — per-clip evidence (`edit_ai.ClipEvidence`): 3 frames over the *whole* clip ([frames](frames.md)), the full RMS [energy curve](segment.md), and top-3 candidate windows.
3. **transcribing** *(if captions enabled)* — full-clip WAV → [transcribe](transcribe.md) per clip with audio.
4. **deciding_edit** — [edit-ai](edit-ai.md) returns a validated edit decision list (`ClipCut(index, start, duration)`) plus an `edit_fallback` flag. Transcript segments are then rebased onto the compilation timeline; slivers straddling a cut boundary (<30% overlap and <0.5 s) are dropped to avoid caption flashes.
5. **analyzing** — [metadata-ai](metadata-ai.md) runs on up to 9 frames from the *used* clips with extra context describing the compilation and the moments used.
6. **rendering** — two-pass render ([render](render.md)):
   - Pass 1 (progress 0→70%): each cut → `build_normalize_command` → mezzanine MP4 with identical codec/fps/1080x1920/48 kHz params, per-clip reframe + loudnorm.
   - Pass 2 (progress 70→100%): concat-demux the mezzanines, then `build_final_command` applies overlays/fades/music — same graph as single-clip but **without loudnorm** (already done per clip).
7. **writing_outputs** — thumbnail is grabbed from the middle of the *final edit* (not a source clip); metadata JSON/txt include a `clips` array (`name`, `source_start`, `duration`, `timeline_start`, `creation_time`) and `edit_fallback`.

## Outputs

`output/compilation_<job_id>/` (web) or `output/compilation_<unix_time>/` (CLI): `<name>_short.mp4`, `thumbnail.jpg`, `<name>_metadata.json`, `<name>_metadata.txt`. Result dict = single-clip keys + `clips` + `edit_fallback`; `source.resolution` is always reported as `1080x1920`, GPS/creation_time come from the first used clip that has them.

## Related

- [Single-clip pipeline](single-clip.md)
- [Edit AI](edit-ai.md) — how the cut list is decided and validated
- [Claude API integration](../integrations/claude-api.md)

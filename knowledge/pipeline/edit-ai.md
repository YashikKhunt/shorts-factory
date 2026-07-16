---
type: Pipeline Stage
title: Edit AI (compilation EDL)
description: Claude chooses which time range of each clip to use in a compilation from frames, transcripts, and energy summaries; output is strictly validated and clamped, with a deterministic energy-based fallback.
tags: [pipeline, ai, claude, edit, compilation, edl]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/edit_ai.py
---

# Edit AI (compilation EDL)

`decide_edit(evidence, target, cfg) → (list[ClipCut], used_fallback)`. Only used by the [compilation pipeline](compilation.md).

## Evidence per clip (`ClipEvidence`)

Index, name, [probe](probe.md) info, 3 frames with their timestamps, the RMS [energy curve](segment.md), top-3 candidate windows, and the timestamped transcript (or None). Sent to Claude as interleaved text/image blocks; the energy curve is pooled into 20 normalized buckets rendered as `t=…:0.xx` pairs.

## Claude call

`messages.parse` (max 2000 tokens) with a JSON-schema-constrained EDL: per clip `{index, use, start, duration, reason}`. The system prompt frames Claude as a short-form editor: hard cuts in given order, prefer speech/action/energy peaks, don't cut mid-sentence, vary pacing, durations must sum to target±2 s, each used range ≥ `compilation.min_clip_seconds` (or the whole clip if shorter). Per-clip decisions are logged to stdout as `[edit] clip N: …`.

## Validation & clamping (`_validate`)

- Ignores unknown/duplicate indices and `use: false` entries; rejects non-finite/negative numbers outright.
- Clamps each cut inside its clip and enforces the per-clip minimum.
- Requires at least `min(2, n_clips)` used clips.
- If total duration is >15% off target, rescales all cuts proportionally (re-clamped); still >target+5 s → reject.
- Output is re-sorted to chronological clip order regardless of how the AI ordered its answer.

Any rejection, API error, missing key, or malformed response → **deterministic fallback**.

## Fallback edit (`fallback_edit`)

Even time split with shortest-first allotment (clips that can't fill their share release time early). Each window is placed on the clip's energy peak via `candidate_windows(k=1)`, or centered when silent. Result is flagged `edit_fallback: true` in job metadata.

## Related

- [Claude API integration](../integrations/claude-api.md)
- [Segment selection](segment.md) — supplies energy curves and the fallback placement

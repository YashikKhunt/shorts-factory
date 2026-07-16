---
type: Pipeline Stage
title: Frame extraction
description: Extracts up to three small representative JPEGs (at 15/50/85% of a window) used as Claude vision evidence and as the UI thumbnail.
tags: [pipeline, frames, ffmpeg, vision]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/frames.py
---

# Frame extraction

`extract_frames(path, start, duration, out_dir) → list[Path]` grabs one frame at each of `FRACTIONS = (0.15, 0.5, 0.85)` of the given window, scaled to 768 px wide (`scale=768:-2`, JPEG `-q:v 3`).

- Individual frame failures are tolerated; only zero successful frames raises `RuntimeError` ("Could not extract any frames from the video") — a hard pipeline failure.
- The small size keeps Claude vision token cost low — see [Claude API integration](../integrations/claude-api.md).

## Consumers

- [metadata-ai](metadata-ai.md) — frames are the primary visual evidence for titles/hashtags/location.
- [edit-ai](edit-ai.md) — compilation evidence; `FRACTIONS` also determines the `frame_times` reported to Claude per clip.
- [Single-clip pipeline](single-clip.md) — copies the middle frame as `thumbnail.jpg` (the [compilation](compilation.md) instead grabs its thumbnail from the final rendered edit).

---
type: Pipeline Stage
title: Captions & hook overlays (Pillow)
description: Rasterizes caption and hook text to transparent 1080-wide PNGs with Pillow, because this ffmpeg build has no libass/drawtext; ffmpeg composites them with timed overlay filters.
tags: [pipeline, captions, hook, pillow, overlays]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/captions.py
---

# Captions & hook overlays (Pillow)

**Why PNGs**: this ffmpeg build has no libass/freetype (no `subtitles`/`drawtext` filters), so text is rasterized in Python with Pillow — which also sidesteps all filtergraph text-escaping issues. To restyle captions, edit `backend/pipeline/captions.py`.

## Mechanics

- Canvas is 1080×1920; text is centered, word-wrapped to 88% of width, white fill with a black stroke (width `max(2, size//14)`), line height 1.25×.
- Font resolution: config font (`captions.font`) is tried as `/System/Library/Fonts/<name>.ttc` first, then a candidate list covering macOS (Avenir Next, Helvetica, Arial Bold) and Linux (DejaVu Sans paths — what Docker uses), preferring the Bold variation inside .ttc collections; final fallback is Pillow's default font.
- `Overlay` dataclass = `(path, start, end, y)`; `y` is the image top edge on the canvas.

## Producers

- `build_hook_overlay(text, cfg, out_dir)` — font size 76, shown 0.2 s → 0.2 + `hook.duration` (default 2.3 s), at 1/5 canvas height.
- `build_caption_overlays(segments, cfg, out_dir)` — one PNG per transcript segment (`captions.size`, default 58), bottom-anchored `captions.bottom_margin` px (default 420 — clear of the YouTube Shorts UI) above the bottom edge minus the image height.

## Consumers

[render](render.md) feeds each PNG as an ffmpeg input and composites it with `overlay=…:enable='between(t,start,end)'` — still images repeat their last frame, so timed enable windows just work. Timing comes from [transcription](transcribe.md) (rebased for [compilations](compilation.md)).

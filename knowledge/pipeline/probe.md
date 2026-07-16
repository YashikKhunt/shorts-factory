---
type: Pipeline Stage
title: Probe (ffprobe)
description: Reads duration, rotation-corrected dimensions, fps, audio presence, HDR flag, GPS, and creation time from an input file via ffprobe JSON.
tags: [pipeline, ffprobe, metadata]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/probe.py
---

# Probe (ffprobe)

`probe(path) → ProbeResult` wraps `ffprobe -print_format json -show_format -show_streams`. Raises `RuntimeError` on unreadable files or files with no video stream — one of the few hard failures in the pipeline.

## What it extracts

- **duration** — from format-level metadata.
- **width/height** — *display* dimensions: swapped when stream rotation (side_data or `rotate` tag) is ±90°, so phone footage reports its upright shape. `aspect` property = w/h.
- **fps** — parsed from `r_frame_rate` fraction, defaults to 30.
- **has_audio** — any audio stream present.
- **is_hdr** — heuristic: 10-bit pixel format (`10le`/`10be`) *and* BT.2020 primaries/colorspace. Consumed by [render](render.md), which applies a saturation boost instead of a true tonemap (this ffmpeg build lacks `zscale` — known limitation).
- **creation_time** — `creation_time` or `com.apple.quicktime.creationdate` tag; used by [compilation](compilation.md) for chronological clip ordering.
- **gps** — parsed from the Apple QuickTime ISO 6709 location tag (or `location`); fed to [metadata-ai](metadata-ai.md) as location evidence.
- **raw** — the full ffprobe dict is kept (excluded from repr).

Format-level tags and video-stream tags are merged, with stream tags winning.

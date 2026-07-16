---
type: External Dependency
title: ffmpeg / ffprobe
description: Required system binaries for probing, audio analysis, frame extraction, and all rendering; startup verifies the overlay, loudnorm, sidechaincompress, and amix filters exist.
tags: [integration, ffmpeg, ffprobe, dependency]
timestamp: 2026-07-16T00:00:00Z
source: backend/config.py, backend/pipeline/render.py
---

# ffmpeg / ffprobe

ffmpeg and ffprobe are hard system requirements (native: `brew install ffmpeg`; Docker: installed in the backend image). The app **raises at startup** if either binary is missing or ffmpeg lacks any of these filters: `overlay`, `loudnorm`, `sidechaincompress`, `amix` ([startup checks](../config/settings.md)).

## Where it's used

- [probe](../pipeline/probe.md) — ffprobe JSON metadata.
- [segment](../pipeline/segment.md) — PCM decode for the audio-energy curve.
- [frames](../pipeline/frames.md) — JPEG frame extraction.
- [transcribe](../pipeline/transcribe.md) callers — WAV extraction (16 kHz mono) before Whisper.
- [render](../pipeline/render.md) — every render pass; progress parsed from `-progress pipe:1`.
- [compilation](../pipeline/compilation.md) — final-edit thumbnail grab.

## Build limitations shaping the code

This ffmpeg build has **no libass/freetype** (no `subtitles`/`drawtext`) — hence Pillow PNG [captions](../pipeline/captions.md) — and **no `zscale`** — hence HDR footage gets a saturation compensation instead of a true tonemap ([render](../pipeline/render.md)). Encoders differ by platform: `h264_videotoolbox` on macOS, `libx264` in Docker.

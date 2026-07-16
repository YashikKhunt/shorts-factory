---
type: Index
title: Video pipeline
description: The two orchestrations (single clip, multi-clip compilation) and the eight stages they compose.
tags: [pipeline, index]
timestamp: 2026-07-16T00:00:00Z
---

# Video pipeline

All processing code lives in `backend/pipeline/`. Two orchestrators compose eight stages; every AI stage has an offline fallback so renders never block on external services.

## Orchestrations

- [Single-clip pipeline](single-clip.md) — one raw clip → one Short, single ffmpeg pass.
- [Compilation pipeline](compilation.md) — 2–8 clips → one AI-edited Short, two-pass render.

## Stages

- [Probe](probe.md) — ffprobe metadata (duration, rotation-aware dims, HDR, GPS, creation time).
- [Segment selection](segment.md) — audio-energy RMS window picking.
- [Transcription](transcribe.md) — faster-whisper with multi-signal no-speech rejection.
- [Frame extraction](frames.md) — representative JPEGs for vision + thumbnails.
- [Metadata AI](metadata-ai.md) — Claude vision → titles/hashtags/hook.
- [Edit AI](edit-ai.md) — Claude → compilation edit decision list, validated + clamped.
- [Captions & hook overlays](captions.md) — Pillow PNG rasterization (no libass).
- [Render](render.md) — all ffmpeg command building and execution.

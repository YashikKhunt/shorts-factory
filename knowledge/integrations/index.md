---
type: Index
title: External integrations
description: The three things the app depends on outside its own code — Claude API, the Whisper model, and the ffmpeg binaries.
tags: [integrations, index]
timestamp: 2026-07-16T00:00:00Z
---

# External integrations

- [Anthropic Claude API](claude-api.md) — vision metadata + compilation edits; the only network service, and fully optional (offline fallbacks).
- [Whisper model (faster-whisper)](whisper.md) — local speech-to-text; one-time ~460 MB model download.
- [ffmpeg / ffprobe](ffmpeg.md) — required binaries; startup verifies the filters the render graph needs.

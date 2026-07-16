---
type: External Service
title: Whisper model (faster-whisper)
description: CPU int8 faster-whisper "small" model for captions — ~460 MB downloaded from HuggingFace on first use and cached; excluded from CI installs.
tags: [integration, whisper, speech, huggingface]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/transcribe.py, docker-compose.yml, requirements.txt
---

# Whisper model (faster-whisper)

Speech-to-text runs locally via the `faster-whisper` package — no external API at inference time, but the model weights download from HuggingFace on first use.

## Facts that matter

- Default model `small` (~460 MB), `int8` compute, CPU only; configurable via the `whisper` config section ([settings](../config/settings.md)).
- **First run needs network access** and a few extra minutes for the download. Cache locations: native — the default HuggingFace cache (`~/.cache/huggingface`); Docker — the `whisper-cache` named volume mounted at `/root/.cache/huggingface`, so the model survives image rebuilds ([Docker deployment](../architecture/docker.md)).
- The model object is a lazy module-level singleton in [transcribe](../pipeline/transcribe.md); the package is imported only when transcription actually runs.
- **Python 3.11 is required** for the project largely because 3.14 lacks faster-whisper wheels.
- CI deliberately installs everything *except* faster-whisper (`grep -v faster-whisper requirements.txt`); tests mock it — see [run-tests](../runbooks/run-tests.md).

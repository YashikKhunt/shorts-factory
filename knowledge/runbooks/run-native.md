---
type: Runbook
title: Run natively (macOS)
description: One-time setup (Python 3.11 venv, deps, frontend build, .env) and the uvicorn command to run the app on http://127.0.0.1:8000, plus the CLI alternative.
tags: [runbook, setup, uvicorn, macos]
timestamp: 2026-07-16T00:00:00Z
source: README.md, backend/scripts/process_one.py
---

# Run natively (macOS)

## One-time setup

```bash
brew install ffmpeg                      # required — see startup filter checks
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv   # MUST be 3.11 (3.14 lacks faster-whisper wheels)
.venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..          # FastAPI serves frontend/dist
cp .env.example .env                     # paste ANTHROPIC_API_KEY (optional — offline fallback without it)
```

Drop royalty-free `.mp3`/`.m4a`/`.wav` tracks into `music/` (or set `music_mode: none` to add YouTube sounds at upload time instead — burned-in music that isn't royalty-free gets Content ID flags).

## Run

```bash
.venv/bin/uvicorn backend.main:app --port 8000
```

Open http://127.0.0.1:8000. First render downloads the ~460 MB Whisper model once ([Whisper](../integrations/whisper.md)).

## CLI (no browser)

```bash
.venv/bin/python -m backend.scripts.process_one path/to/clip.mov            # single clip
.venv/bin/python -m backend.scripts.process_one --combine a.mov b.mov c.mov # compilation
```

Outputs land in `output/<clip>/`: `_short.mp4`, `_metadata.txt` (titles / hashtag line / hook), `_metadata.json`, `thumbnail.jpg`.

## Related

- [Run with Docker](run-docker.md) — zero local Python/ffmpeg/node
- [Settings](../config/settings.md) — tuning knobs

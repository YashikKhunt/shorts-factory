---
type: Runbook
title: Run with Docker
description: docker compose up --build; UI on http://localhost:3000; outputs/uploads/music/data bind-mounted to the host; Whisper model cached in a named volume.
tags: [runbook, docker, compose]
timestamp: 2026-07-16T00:00:00Z
source: README.md, docker-compose.yml
---

# Run with Docker

No local Python/ffmpeg/node needed.

```bash
cp .env.example .env        # optional — ANTHROPIC_API_KEY for AI titles
docker compose up --build
```

Open **http://localhost:3000** (nginx frontend; the backend is not exposed — see [Docker deployment](../architecture/docker.md)).

## Operational notes

- Rendered Shorts land in `./output/` on the host; uploads in `./uploads/`; job list persists in `./data/jobs.json`.
- Music goes in `./music/` — **restart the backend after adding tracks** (music presence is checked at startup).
- First render downloads the ~460 MB Whisper model into the `whisper-cache` volume (one time, needs network) — [Whisper](../integrations/whisper.md).
- The container runs `docker/config.docker.yaml` (libx264 encoder, DejaVu Sans captions).
- "Reveal in Finder" is a no-op in Docker; use the download button.
- The frontend waits for the backend healthcheck (`GET /api/jobs`) before starting.

## Related

- [Run natively](run-native.md)

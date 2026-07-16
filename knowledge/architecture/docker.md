---
type: Deployment
title: Docker deployment
description: Two-container setup — nginx frontend (port 3000) proxying /api to an internal FastAPI backend — with host bind mounts and a Whisper model cache volume.
tags: [docker, deployment, nginx, compose]
timestamp: 2026-07-16T00:00:00Z
source: docker-compose.yml, docker/backend.Dockerfile, docker/frontend.Dockerfile, docker/nginx.conf, docker/config.docker.yaml
---

# Docker deployment

`docker compose up --build` runs two containers on a private bridge network `shorts-net`. **Only the frontend is exposed** (host port 3000 → nginx 80); the backend's port 8000 stays internal.

## Containers

- **backend** (`docker/backend.Dockerfile`) — Python + ffmpeg + the FastAPI app. Healthcheck hits `http://127.0.0.1:8000/api/jobs`; the frontend waits for `service_healthy`. `.env` is optional (`required: false`) — without `ANTHROPIC_API_KEY` the app degrades to offline metadata.
- **frontend** (`docker/frontend.Dockerfile` + `docker/nginx.conf`) — builds the React app and serves it via nginx, proxying `/api` to `backend:8000`.

## Volumes

| Mount | Purpose |
|---|---|
| `./uploads:/app/uploads` | incoming clips |
| `./output:/app/output` | rendered Shorts land on the host |
| `./music:/app/music` | background music (restart backend after adding tracks) |
| `./data:/app/data` | `jobs.json` persistence (`JOBS_SNAPSHOT` points here) |
| `whisper-cache:/root/.cache/huggingface` | named volume; ~460 MB Whisper model survives rebuilds |

## Linux config deltas (`docker/config.docker.yaml`, baked in as `/app/config.yaml`)

Only two differences from the macOS `config.yaml`:

- `video.encoder: libx264` — `h264_videotoolbox` doesn't exist on Linux.
- `captions.font: DejaVu Sans` — no Avenir Next; [captions](../pipeline/captions.md) fall through its font candidate list to the DejaVu paths.

## Gotchas

- First render needs network access + a few minutes to download the Whisper model — see [Whisper integration](../integrations/whisper.md).
- "Reveal in Finder" is a no-op inside Docker (no `open` binary); use the download button.
- A native macOS `jobs.json` isn't carried over (absolute mac paths); rendered outputs in `./output/` are unaffected.

## Related

- [Run with Docker](../runbooks/run-docker.md)
- [Backend API](backend-api.md), [Frontend](frontend.md), [Job queue](job-queue.md)

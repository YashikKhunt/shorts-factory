---
type: Service
title: Backend API (FastAPI)
description: FastAPI app exposing the upload/jobs/config API, running the single processing worker, and serving the built frontend in native mode.
tags: [backend, fastapi, api, service]
timestamp: 2026-07-16T00:00:00Z
source: backend/main.py
---

# Backend API (FastAPI)

The backend is a single FastAPI app (`backend/main.py`, `app = FastAPI(title="Shorts Factory")`) started with `uvicorn backend.main:app`. It has three responsibilities:

1. **HTTP API** — all routes live under `/api/*`; see [API endpoints](../api/endpoints.md) for the full list.
2. **Background worker** — the app's `lifespan` context runs [startup checks](../config/settings.md), loads the persisted job snapshot, and spawns exactly one `asyncio` task running `jobs.worker(cfg)` — see [Job queue](job-queue.md). The task is cancelled on shutdown.
3. **Static frontend** — if `frontend/dist/` exists, it is mounted at `/` with `StaticFiles(html=True)`, so in native mode one port (8000) serves both the UI and the API. In Docker, nginx serves the UI instead — see [Docker deployment](docker.md).

## Key behaviors

- Config is loaded once at import time (`cfg = load_settings()`); `PUT /api/config` mutates this live object in memory only (never written back to `config.yaml`).
- Startup warnings (missing music, missing `ANTHROPIC_API_KEY`) are collected in `startup_warnings` and returned with every `GET /api/jobs` response so the [frontend](frontend.md) can display them.
- Uploads are filtered by extension (`.mp4 .mov .m4v .avi .mkv .webm`), streamed to disk in 1 MiB chunks, and filenames are sanitized (`[^A-Za-z0-9._-] → _`). Each job gets its own directory `uploads/<job_id>/`.
- With `combine=1` and ≥2 valid files, one compilation job is created instead of N single jobs; files are prefixed `00_`, `01_`, … to preserve selection order. Upload count is capped by `compilation.max_clips` (default 8).
- `POST /api/jobs/{id}/reveal` shells out to macOS `open -R`; it is a silent no-op where the `open` binary doesn't exist (Docker/Linux).

## Related

- [Job queue and persistence](job-queue.md)
- [Single-clip pipeline](../pipeline/single-clip.md) and [Compilation pipeline](../pipeline/compilation.md) — the work the worker dispatches
- [Configuration](../config/settings.md)

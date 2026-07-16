---
type: Service
title: Frontend (React + Vite)
description: Drag-and-drop React 18 UI that uploads clips, polls job status every 1.5s, and presents titles/hashtags/download for finished Shorts.
tags: [frontend, react, vite, ui]
timestamp: 2026-07-16T00:00:00Z
source: frontend/src
---

# Frontend (React + Vite)

React 18.3 single-page app built with Vite 5 (`frontend/`). No UI framework — plain CSS in `frontend/src/styles.css`.

## Structure

- `frontend/src/App.jsx` — top-level layout and state.
- `frontend/src/api.js` — all server communication:
  - `uploadFiles(files, combine)` — multipart `POST /api/upload` with a `combine` form flag ("1"/"0").
  - `usePolling(intervalMs = 1500)` — hook that polls `GET /api/jobs` every 1.5 s, returns `{jobs, warnings}`; skips overlapping requests and silently tolerates fetch failures (server restarts).
  - `deleteJob(id)` / `revealJob(id)` — thin wrappers over `DELETE /api/jobs/{id}` and `POST /api/jobs/{id}/reveal`.
- `frontend/src/components/DropZone.jsx` — drag-drop target with the "combine into one Short" toggle.
- `frontend/src/components/JobCard.jsx` — per-job status, stage label, and render progress bar.
- `frontend/src/components/ResultPanel.jsx` — title options, paste-ready hashtags, thumbnail, download/reveal buttons.

## How it reaches the backend

All requests use relative `/api/...` URLs, so the same build works in both deployments:

- **Native**: FastAPI serves `frontend/dist/` on the same origin — see [Backend API](backend-api.md).
- **Docker**: nginx serves the static build and proxies `/api` to the backend container — see [Docker deployment](docker.md).

There is no websocket/SSE — job progress is purely poll-driven, which matches the backend design where stage/progress fields are plain mutable job attributes ([Job queue](job-queue.md)).

## Related

- [API endpoints](../api/endpoints.md)
- [Run natively](../runbooks/run-native.md) (requires `npm run build` first)

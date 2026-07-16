---
type: API
title: HTTP API endpoints
description: The complete /api surface — upload, job listing/status/results, deletion, reveal, and live config get/put.
tags: [api, http, endpoints, fastapi]
timestamp: 2026-07-16T00:00:00Z
source: backend/main.py
---

# HTTP API endpoints

All routes are defined in `backend/main.py` on the [Backend API](../architecture/backend-api.md). Job objects in responses are `Job.public()` — no filesystem paths ([Job queue](../architecture/job-queue.md)).

| Method & path | Behavior |
|---|---|
| `POST /api/upload` | Multipart `files[]` + `combine` form field (`"1"/"true"/"on"` enables). Filters to video extensions (`.mp4 .mov .m4v .avi .mkv .webm`); 400 if none valid. Combine + ≥2 files → one compilation job (400 if > `compilation.max_clips`); otherwise one job per file. Returns `{"jobs": [...]}`. |
| `GET /api/jobs` | All jobs, newest first, plus `warnings` (startup warnings shown by the UI). Polled every 1.5 s by the [frontend](../architecture/frontend.md). |
| `GET /api/jobs/{id}` | One job; 404 if unknown. |
| `GET /api/jobs/{id}/video` | The rendered MP4 (`video/mp4`); 404 until the job is done or if the file vanished from disk. |
| `GET /api/jobs/{id}/thumbnail` | `thumbnail.jpg` for the job. |
| `GET /api/jobs/{id}/download` | Same MP4 with a `filename=` disposition for save-as. |
| `POST /api/jobs/{id}/reveal` | macOS `open -R` on the output file; silent no-op without the `open` binary (Docker). Always `{"ok": true}` if the result exists. |
| `DELETE /api/jobs/{id}` | Removes the job from the registry and snapshot (output files on disk are not deleted). |
| `GET /api/config` | Live subset: `music_mode`, `target_duration`, `segment_strategy`, `aspect_strategy`, `captions_enabled`, `hook_enabled`, `claude_model`, `api_key_set`. |
| `PUT /api/config` | Updates any of those keys (except `api_key_set`) on the **in-memory** settings object — not persisted to `config.yaml`, resets on restart. Returns the new config. |

## Notes

- No auth — the app is designed for localhost / private-network use.
- There is no cancel endpoint; a running render can't be stopped via the API.

## Related

- [Configuration](../config/settings.md) — the full (much larger) config surface behind the `PUT /api/config` subset

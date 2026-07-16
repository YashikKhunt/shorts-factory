---
type: Component
title: Job queue and persistence
description: Single-worker asyncio queue that renders one video at a time, with job state persisted to jobs.json across restarts.
tags: [backend, jobs, queue, persistence]
timestamp: 2026-07-16T00:00:00Z
source: backend/jobs.py
---

# Job queue and persistence

`backend/jobs.py` holds the job model, the in-memory registry, and the worker loop. **One video renders at a time by design** — a single `asyncio.Queue` drained by a single worker task (started by the [Backend API](backend-api.md) lifespan).

## Job model

`Job` dataclass: `id` (12-hex uuid prefix), `filename`, `src_path`, `status` (`queued | running | done | error`), `stage`, `progress` (0–100, only meaningful while `stage == "rendering"`), `error`, `result` (dict from the pipeline), `created_at`, `src_paths` (2+ entries ⇒ compilation job).

`Job.public()` strips `src_path`/`src_paths` — API responses never expose server filesystem paths.

## Worker loop

- Pops a job id, skips it unless still `queued`, sets `running`.
- Dispatches by `len(job.src_paths)`: >1 → [`process_compilation`](../pipeline/compilation.md), else → [`process_video`](../pipeline/single-clip.md).
- Heavy work runs via `loop.run_in_executor(None, ...)` — ffmpeg/Whisper/Claude never block the event loop, so the API stays responsive mid-render.
- Stage callbacks mutate `job.stage`/`job.progress` in place; the polling API reads them directly. Progress resets to 0 on every non-`rendering` stage change.
- Any exception marks the job `error` (message truncated to 500 chars) and **keeps the worker alive** for the next job.

## Persistence

- Snapshot file: `jobs.json` at project root, overridable via the `JOBS_SNAPSHOT` env var (Docker sets it under `/app/data/` — see [Docker deployment](docker.md)).
- Saved on every job create/finish/delete; write failures (`OSError`) are silently ignored.
- On startup, `load_snapshot()` restores jobs; anything that was `running` when the server died is marked `error: "Interrupted by server restart"` — interrupted jobs are **not** re-queued.
- A `jobs.json` written by native macOS runs is not portable into Docker (it stores absolute host paths).

## Related

- [Backend API](backend-api.md) — creates jobs and enqueues them
- [Configuration](../config/settings.md)

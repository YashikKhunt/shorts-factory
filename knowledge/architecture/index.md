---
type: Index
title: Architecture
description: The system's moving parts — backend service, frontend, job queue, and the Docker deployment.
tags: [architecture, index]
timestamp: 2026-07-16T00:00:00Z
---

# Architecture

Shorts Factory is a two-tier local app: a React UI talking to a FastAPI backend that runs one video render at a time.

- [Backend API (FastAPI)](backend-api.md) — the `/api` surface, worker startup, static frontend serving.
- [Frontend (React + Vite)](frontend.md) — drag-drop upload, 1.5 s status polling, results panel.
- [Job queue and persistence](job-queue.md) — the single-worker queue and the `jobs.json` snapshot.
- [Docker deployment](docker.md) — nginx + backend containers, volumes, Linux config deltas.

The video processing itself lives in the [pipeline](../pipeline/index.md) section.

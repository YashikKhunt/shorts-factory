---
type: Project
title: Shorts Factory
description: Local app that turns raw trip videos into ready-to-post YouTube Shorts — trimmed, 9:16, with music, captions, a hook overlay, and AI-generated titles/hashtags.
tags: [project, overview, okf]
timestamp: 2026-07-16T00:00:00Z
resource: https://github.com/YashikKhunt/shorts-factory
source: README.md
---

# Shorts Factory — knowledge base

Drop raw trip videos in; get ready-to-post YouTube Shorts out: trimmed to the best ~25 seconds, 9:16 vertical, background music, auto captions, an on-video hook line, and 3 AI-generated title options with curated hashtags. Uploading to YouTube Studio stays manual by design — that lets the user attach trending YT sounds, which no API can do.

The system is a React drag-drop UI over a FastAPI backend that renders **one video at a time** through an ffmpeg/Whisper/Claude pipeline. Two invariants shape almost every module: (1) heavy work runs in a thread executor behind a single-worker queue so the API stays responsive, and (2) every AI stage has an offline fallback, so a render never blocks on the Anthropic API, missing music, or absent speech. It runs natively on macOS or as two Docker containers.

This directory is an [Open Knowledge Format](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing/) (OKF v0.1) bundle: each file is one typed concept with YAML frontmatter; follow the links below progressively rather than reading everything. `source:` in each file's frontmatter names the repo files it documents. Changes are tracked in [log.md](log.md).

## Sections

- [Architecture](architecture/index.md) — [backend API](architecture/backend-api.md), [frontend](architecture/frontend.md), [job queue](architecture/job-queue.md), [Docker deployment](architecture/docker.md).
- [Video pipeline](pipeline/index.md) — the [single-clip](pipeline/single-clip.md) and [compilation](pipeline/compilation.md) orchestrations and their eight stages.
- [API endpoints](api/endpoints.md) — the complete `/api` surface.
- [Settings](config/settings.md) — `config.yaml` + `.env`, startup checks, live-editable subset.
- [External integrations](integrations/index.md) — [Claude API](integrations/claude-api.md), [Whisper](integrations/whisper.md), [ffmpeg](integrations/ffmpeg.md).
- [Runbooks](runbooks/index.md) — [run natively](runbooks/run-native.md), [run with Docker](runbooks/run-docker.md), [tests & CI](runbooks/run-tests.md).

## Known limitations (project-wide)

- HDR (10-bit) footage gets saturation compensation, not a true tonemap (no `zscale` in this ffmpeg build).
- Captions/hook are Pillow PNG overlays (no libass/drawtext) — styling lives in code, not config.
- One render at a time by design; no render cancellation via the API.
- Python **3.11** required (3.14 lacks faster-whisper wheels).

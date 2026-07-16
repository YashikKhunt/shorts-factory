---
type: Configuration
title: Settings (config.yaml + .env)
description: Pydantic-validated settings loaded from config.yaml and .env, the startup environment checks, and which knobs control what.
tags: [config, settings, yaml, env]
timestamp: 2026-07-16T00:00:00Z
source: backend/config.py, config.yaml, docker/config.docker.yaml
---

# Settings (config.yaml + .env)

`backend/config.py` loads `config.yaml` at project root into a Pydantic v2 `Settings` model (unknown/missing keys fall back to model defaults) and `.env` via python-dotenv. Relative paths resolve against the project root; `music/`, `output/`, `uploads/` are created if missing. **`ANTHROPIC_API_KEY` comes only from the environment/.env**, exposed as the `Settings.anthropic_api_key` property — it is never in YAML.

## Sections and key knobs (defaults from `config.yaml`)

- **paths** — `music_dir`, `output_dir`, `uploads_dir`.
- **video** — `target_duration: 25`; `segment_strategy: energy|first` ([segment](../pipeline/segment.md)); `aspect_strategy: crop|pad`; `color_grade {enabled, saturation 1.15, contrast 1.05}`; `fade {in 0.4, out 0.5}`; `fps: 30`; `encoder: h264_videotoolbox|libx264` (+ `bitrate: 10M` for videotoolbox, `crf: 18` for libx264) — all consumed by [render](../pipeline/render.md).
- **audio** — `music_mode: duck|mix|replace|none`; `music_gain_db: -14`; `loudnorm_target: -14` (LUFS).
- **captions** — `enabled`, `font: Avenir Next` (Docker: DejaVu Sans), `size: 58`, `bottom_margin: 420` px (clear of the YT Shorts UI) — see [captions](../pipeline/captions.md).
- **hook** — `enabled`, `duration: 2.3` s, `fallback_text: "Wait for it…"`.
- **whisper** — `model: small`, `compute_type: int8`, plus no-speech thresholds `min_speech_seconds: 1.5`, `max_no_speech_prob: 0.6` ([transcribe](../pipeline/transcribe.md)).
- **claude** — `model: claude-sonnet-5` (~$0.01/video; `claude-haiku-4-5` for bulk), `title_count: 3` ([Claude integration](../integrations/claude-api.md)).
- **compilation** — `min_clip_seconds: 3.0`, `max_clips: 8` ([compilation](../pipeline/compilation.md)).
- **hashtags** — `broad` list (always seeded with `#shorts #travel`), `niche_hint` ([metadata-ai](../pipeline/metadata-ai.md)).

## Startup checks (`startup_checks`)

Fatal (raise): `ffmpeg`/`ffprobe` missing, or ffmpeg lacking any of the `overlay`, `loudnorm`, `sidechaincompress`, `amix` filters — see [ffmpeg](../integrations/ffmpeg.md). Warnings (returned, shown in UI): no music files while `music_mode != none` (auto-switches to `none`), and no `ANTHROPIC_API_KEY` (offline metadata fallback).

## Runtime mutation

`PUT /api/config` ([endpoints](../api/endpoints.md)) edits 7 whitelisted fields on the in-memory object only; changes are lost on restart. The Docker image bakes in `docker/config.docker.yaml` instead (libx264 + DejaVu Sans — see [Docker deployment](../architecture/docker.md)). Env var `JOBS_SNAPSHOT` relocates the jobs.json snapshot ([Job queue](../architecture/job-queue.md)).

---
type: External Service
title: Anthropic Claude API
description: Claude vision powers metadata generation and compilation edit decisions via structured outputs; both call sites degrade to offline fallbacks so renders never block on the API.
tags: [integration, anthropic, claude, ai, vision]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/metadata_ai.py, backend/pipeline/edit_ai.py
---

# Anthropic Claude API

The `anthropic` Python SDK (>=0.40) is used in exactly **two places**, both vision calls with structured outputs (`client.messages.parse` + `output_config: {format: {type: json_schema, schema: ...}}` so responses are schema-guaranteed):

1. [metadata-ai](../pipeline/metadata-ai.md) — frames + GPS + transcript → titles/hashtags/hook/location (max 1024 tokens).
2. [edit-ai](../pipeline/edit-ai.md) — per-clip frames/energy/transcript evidence → compilation EDL (max 2000 tokens).

## Configuration & cost

- Model from `claude.model` (default `claude-sonnet-5`, ~$0.01 per video; `claude-haiku-4-5` recommended for bulk) — editable live via `PUT /api/config`.
- Auth: `ANTHROPIC_API_KEY` in `.env`/environment (the SDK's default `anthropic.Anthropic()` pickup). `cfg_key_present()` in `metadata_ai.py` gates both call sites.
- Frames are sent as base64 JPEGs downscaled to 768 px wide ([frames](../pipeline/frames.md)) to keep vision token cost low.

## Failure policy (core invariant)

**A render must never block on Claude.** Both call sites catch `APIStatusError`, `APIConnectionError`, and response-shape errors, log a one-line `[metadata]`/`[edit]` message to stdout, and fall back:

- metadata → templated titles/hashtags from the filename (`fallback: true` in results),
- edit → deterministic energy-split cuts (`edit_fallback: true`).

There are no retries and no timeouts beyond SDK defaults — failures immediately use the fallback.

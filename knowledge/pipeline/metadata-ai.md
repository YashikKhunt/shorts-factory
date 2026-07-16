---
type: Pipeline Stage
title: Metadata AI (titles, hashtags, hook)
description: Claude vision turns frames + GPS + transcript into titles, hashtags, an on-video hook line, and a location guess — with a guaranteed offline fallback.
tags: [pipeline, ai, claude, metadata, titles, hashtags]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/metadata_ai.py
---

# Metadata AI (titles, hashtags, hook)

`generate_metadata(frames, info, src_name, transcript_segments, cfg, extra_context) → VideoMetadata`.

## Claude call

- One `client.messages.parse()` call (model `claude.model`, max 1024 tokens) with base64 JPEG frames + a text context block (duration, creation time, GPS coordinates, transcript or "No speech", plus any `extra_context` lines from the [compilation](compilation.md)).
- **Structured outputs**: `output_config.format = json_schema` guarantees the shape — `titles[]`, `hashtags[]`, `hook`, `location_guess|null`. If `parsed_output` is None it falls back to parsing the first text block as JSON.
- The system prompt encodes the content strategy: exactly `claude.title_count` titles under 70 chars using engagement patterns (curiosity gap, POV, place+superlative, question hook, ≤1 emoji); 8–12 lowercase hashtags starting `#shorts #travel` then broad pool (`hashtags.broad`) then niche/location tags (`hashtags.niche_hint`); hook ≤6 punchy words that complements (not duplicates) titles.
- Token usage is recorded in `VideoMetadata.extra["usage"]`.

## Fallback (never blocks the render)

`cfg_key_present(cfg)` false (no `ANTHROPIC_API_KEY`), any `APIStatusError`/`APIConnectionError`, or a malformed response → `_fallback_metadata`: templated titles from the humanized filename stem, `#shorts #travel` + `hashtags.broad` (deduped), and `hook.fallback_text` ("Wait for it…"). The result carries `fallback: True`, surfaced as `metadata_fallback` in job results and flagged in `_metadata.txt`.

`cfg_key_present` is also imported by [edit-ai](edit-ai.md) for the same gate.

## Related

- [Claude API integration](../integrations/claude-api.md) — models, cost, error taxonomy
- [Frames](frames.md), [Transcription](transcribe.md), [Probe](probe.md) — the evidence inputs

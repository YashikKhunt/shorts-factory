---
type: Pipeline Stage
title: Transcription (faster-whisper)
description: Transcribes a WAV with faster-whisper and rejects the result unless several independent signals agree there is real speech, to suppress Whisper hallucinations on ambient audio.
tags: [pipeline, whisper, transcription, captions]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/transcribe.py
---

# Transcription (faster-whisper)

`transcribe(wav, cfg) → [(start, end, text)] | None`. Returning `None` means "no usable speech" — downstream, captions are simply skipped and metadata says "No speech — ambient trip footage."

## No-speech detection (the important part)

Raw trip footage is usually wind/ambience, and Whisper hallucinates phrases like "Thanks for watching" on it. A transcript is only trusted when it passes **all** of:

1. Total speech duration ≥ `whisper.min_speech_seconds` (default 1.5 s).
2. Mean `no_speech_prob` across segments ≤ `whisper.max_no_speech_prob` (default 0.6).
3. Not (fewer than 4 words **and** every segment `avg_logprob < -1.0`).

VAD filtering (`vad_filter=True`) is also enabled; empty segment lists return `None` immediately.

## Model handling

- Lazy singleton: `WhisperModel` is constructed on first use and cached at module level, keyed on `(whisper.model, whisper.compute_type)` — changing config at runtime reloads it.
- Defaults: model `small` (~460 MB download on first run), `int8` compute, CPU. See [Whisper integration](../integrations/whisper.md) for caching.
- `faster-whisper` is imported *inside* `_get_model`, which is why CI can run without the package installed ([run-tests](../runbooks/run-tests.md)).

## Callers

[Single-clip](single-clip.md) transcribes only the selected window; [compilation](compilation.md) transcribes each full clip (times are clip-absolute and later rebased onto the compilation timeline).

---
type: Pipeline Stage
title: Render (ffmpeg)
description: Builds and runs all ffmpeg commands — the single-pass Short render, the compilation's per-clip mezzanine pass, and the concat+finish pass — including the 9:16 reframe, color grade, overlays, fades, and music ducking graph.
tags: [pipeline, ffmpeg, render, audio, encoding]
timestamp: 2026-07-16T00:00:00Z
source: backend/pipeline/render.py
---

# Render (ffmpeg)

`backend/pipeline/render.py` is the only place ffmpeg render commands are built. Three command builders share helper graph functions:

## Shared video chain (`_video_norm_chain`)

`fps=<video.fps>` → 9:16 reframe → optional color grade → `format=yuv420p`.

- **Reframe** (`_aspect_filters`): already ~9:16 → plain scale to 1080×1920; `crop` strategy → scale-to-cover + center crop; `pad` → scale-to-fit + black letterbox.
- **Color grade**: `eq=saturation:contrast` from `video.color_grade`; HDR sources ([probe](probe.md) `is_hdr`) get an extra 1.1× saturation as compensation — this ffmpeg build lacks `zscale` for a true tonemap (known limitation).

## Audio graph (`_audio_graph`)

Original audio gets `loudnorm=I=<audio.loudnorm_target>:TP=-1.5:LRA=11`. Music (random track via `pick_music`, stream-looped, `audio.music_gain_db`, 0.6 s/0.8 s fades) combines per `audio.music_mode`:

- `duck` — `sidechaincompress` (threshold .05, ratio 8, attack 20, release 400) keyed by the original audio, then `amix`.
- `mix` — plain `amix`.
- `replace` — music only (also used when the source is silent).
- `none` / no tracks — original only; if there's no audio at all, a silent `anullsrc` stereo track is injected so outputs always have an audio stream.

## The three builders

1. `build_command` — single-clip pass: inputs are [0] seeked/trimmed source, [1..n] overlay PNGs ([captions](captions.md), composited with timed `enable` windows), [last] looped music. Video fade in/out from `video.fade`. Encoder per `video.encoder`: `h264_videotoolbox -b:v <bitrate>` (macOS) or `libx264 -crf <crf> -preset medium` (Docker). AAC 192k, `+faststart`.
2. `build_normalize_command` — compilation pass 1: one cut → mezzanine with identical params (1080×1920, cfg fps, yuv420p, 48 kHz stereo AAC 256k) so concat can join them; loudnorm per clip; slightly higher quality (crf−4, veryfast) since it's re-encoded once more; silent clips get anullsrc audio here.
3. `build_final_command` — compilation pass 2: `-f concat -safe 0` demux of the mezzanines, then the same overlay/fade/music graph **without loudnorm** (done in pass 1); the concat stream always has audio (pass 1 guarantees it).

## Execution

`run_render(cmd, duration, on_progress)` parses `-progress pipe:1` output (`out_time_us`) into a 0–100% callback; nonzero exit raises `RuntimeError` with the last 400 chars of stderr.

## Related

- [ffmpeg dependency](../integrations/ffmpeg.md) — required filters checked at startup
- [Single-clip](single-clip.md) / [Compilation](compilation.md) — callers

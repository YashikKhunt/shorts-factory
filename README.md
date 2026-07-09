# Shorts Factory

Drop raw trip videos in — get ready-to-post YouTube Shorts out: trimmed to the
best ~25 seconds, 9:16 vertical, background music, auto captions, an on-video
hook line, and 3 AI-generated title options with curated hashtags. You upload
the result to YouTube Studio yourself (that also lets you attach trending YT
sounds, which no API can do).

## Setup (one time)

```bash
brew install ffmpeg                      # if not installed
cd shorts-factory
/opt/homebrew/opt/python@3.11/bin/python3.11 -m venv .venv   # Python 3.11 (3.14 lacks faster-whisper wheels)
.venv/bin/pip install -r requirements.txt
cd frontend && npm install && npm run build && cd ..
cp .env.example .env                     # then paste your Anthropic API key
```

- **API key**: get one at https://console.anthropic.com/ and put it in `.env`.
  Without it everything still works, but titles/hashtags use offline templates.
- **Music**: drop royalty-free `.mp3`/`.m4a`/`.wav` tracks into `music/`.
  ⚠️ Burned-in music must be genuinely royalty-free or Content ID will flag
  your Shorts. If you prefer adding YouTube sounds at upload time, set
  `music_mode: none` in `config.yaml`.
- First run downloads the Whisper `small` speech model (~460 MB, one time).

## Run

```bash
.venv/bin/uvicorn backend.main:app --port 8000
```

Open http://127.0.0.1:8000 — drag your videos in, watch the queue, then copy a
title + hashtags and download the finished Short.

CLI alternative (no browser):

```bash
.venv/bin/python -m backend.scripts.process_one path/to/clip.mov
```

Outputs land in `output/<clip>/`: the `_short.mp4`, a human-readable
`_metadata.txt` (titles / paste-ready hashtag line / hook), and `_metadata.json`.

## Tuning (`config.yaml`)

| Setting | What it does |
|---|---|
| `video.target_duration` | Length of the finished Short (default 25s) |
| `video.segment_strategy` | `energy` picks the loudest/liveliest window; `first` takes the start |
| `video.aspect_strategy` | `crop` (fill 9:16) or `pad` (letterbox) |
| `audio.music_mode` | `duck` (music dips under original audio), `mix`, `replace`, `none` |
| `captions.enabled` | Whisper captions on/off (auto-skipped when there's no speech) |
| `hook.enabled` / `fallback_text` | On-video hook overlay in the first ~2.5s |
| `claude.model` | `claude-sonnet-5` default (~$0.01/video); drop to `claude-haiku-4-5` for bulk |
| `hashtags.broad` / `niche_hint` | Steers the AI's hashtag picks |

## Known limitations

- HDR (10-bit) iPhone footage gets a saturation compensation rather than a true
  tonemap — this ffmpeg build lacks `zscale`. If HDR clips look washed out,
  record in SDR or re-export first.
- Captions/hook are rendered as PNG overlays via Pillow (this ffmpeg build has
  no libass/drawtext) — style them in `backend/pipeline/captions.py`.
- One video renders at a time by design; a 25s clip takes a few seconds plus
  Whisper/Claude time.

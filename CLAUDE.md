# Shorts Factory

Local app that turns raw trip videos into ready-to-post YouTube Shorts: a React drag-drop UI over a FastAPI backend that renders one video at a time through an ffmpeg / Whisper / Claude pipeline (trim to ~25s, 9:16 reframe, music, captions, hook overlay, AI titles/hashtags). Runs natively on macOS or via `docker compose up`.

## Project knowledge base (OKF)

Curated project knowledge lives in `knowledge/` as an **Open Knowledge Format** bundle — one typed markdown concept per file, linked into a graph.

- **Start at `knowledge/index.md`** and follow links to just the concepts relevant to your task (progressive disclosure) — don't read the whole bundle.
- Each concept's `source:` frontmatter names the repo files it documents; trust the source code over the concept file if they disagree, and fix the concept file.
- **When you change architecture, endpoints, config keys, pipeline behavior, or dependencies: update the affected concept file(s) and add a dated entry to `knowledge/log.md`** in the same change.

## Committing code

- Never commit directly to `main` — create or use a feature branch first.
- After completing code changes in a turn, run a review of the working tree
  following the checklist in `.claude/agents/post-agent-reviewer.md` (the
  reviewer only reports; it never commits).
- Then commit ALL modified and new files on the branch — no files may be
  left uncommitted at the end of a turn.

## Ground rules

- Python 3.11 (`faster-whisper` has no wheels for newer versions); venv at `.venv/`.
- Tests: `python -m pytest test --cov=backend` — tests mock faster-whisper; CI installs deps without it.
- Renders must never block on the Anthropic API — every AI stage keeps its offline fallback.

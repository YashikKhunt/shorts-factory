---
type: Runbook
title: Run tests & CI
description: pytest suite in test/ (unit + API tests, faster-whisper mocked) run locally with coverage, and the GitHub Actions workflow that runs it on Python 3.11.
tags: [runbook, tests, pytest, ci, github-actions]
timestamp: 2026-07-16T00:00:00Z
source: test/, .github/workflows/tests.yml, test/requirements-dev.txt
---

# Run tests & CI

## Locally

```bash
.venv/bin/pip install -r test/requirements-dev.txt
.venv/bin/python -m pytest test --cov=backend --cov-report=term-missing
```

Layout: `test/unit/` (12 files covering the pipeline modules), `test/api/test_main.py` (FastAPI endpoints), shared fixtures in `test/conftest.py`. Sample media lives in `test_assets/` (horizontal_40s, silent_4x3_30s, speech_15s, vertical_20s MP4s).

## CI (`.github/workflows/tests.yml`)

- Triggers: push to `main` and every pull request.
- Ubuntu, Python 3.11 with pip cache.
- **Installs `requirements.txt` minus `faster-whisper`** (`grep -v faster-whisper`) plus `test/requirements-dev.txt` — tests mock Whisper, and the lazy import in [transcribe](../pipeline/transcribe.md) makes that safe.
- Runs `pytest test --cov=backend --cov-report=term-missing` with the pytest cache redirected into `test/`, and appends the last 40 lines of output (coverage table) to the job summary — even on failure.
- README shows the workflow badge.

## Conventions

- The `test-writer` Claude Code agent (`.claude/agents/test-writer.md`) writes only into `test/` and never touches production source.

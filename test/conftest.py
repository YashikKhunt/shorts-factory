"""Shared pytest fixtures for the shorts-factory backend test suite.

Design notes:
- The repo root is inserted onto sys.path so `import backend...` works no
  matter what directory pytest is invoked from.
- `ANTHROPIC_API_KEY` is stripped from the environment for every test by
  default (this dev machine's real .env has a live key loaded into
  os.environ via backend.config's module-level `load_dotenv` call). Tests
  that need "key present" behavior must explicitly `monkeypatch.setenv(...)`
  AND mock out `anthropic.Anthropic` — no test may ever hit the real
  Anthropic API.
- All fixtures build `Settings` objects pointed at pytest's `tmp_path`, so
  nothing is ever written under the real repo's music/output/uploads dirs.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402

from backend.config import Settings, Paths  # noqa: E402
from backend.pipeline.probe import ProbeResult  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_api_key(monkeypatch):
    """Never let a real Anthropic key leak into a test's default behavior."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def cfg_factory(tmp_path):
    """Returns a callable that builds a Settings object rooted at tmp_path.

    Usage: cfg = cfg_factory()  or  cfg = cfg_factory(video={"target_duration": 10})
    """
    def _make(**overrides) -> Settings:
        music_dir = tmp_path / "music"
        output_dir = tmp_path / "output"
        uploads_dir = tmp_path / "uploads"
        for d in (music_dir, output_dir, uploads_dir):
            d.mkdir(parents=True, exist_ok=True)
        base = {"paths": Paths(music_dir=music_dir, output_dir=output_dir,
                                uploads_dir=uploads_dir)}
        base.update(overrides)
        return Settings(**base)
    return _make


@pytest.fixture
def cfg(cfg_factory):
    return cfg_factory()


@pytest.fixture
def probe_factory():
    """Returns a callable that builds a ProbeResult with sane defaults."""
    def _make(duration=20.0, width=1920, height=1080, fps=30.0,
              has_audio=True, is_hdr=False, creation_time=None,
              gps=None, raw=None) -> ProbeResult:
        return ProbeResult(duration=duration, width=width, height=height,
                           fps=fps, has_audio=has_audio, is_hdr=is_hdr,
                           creation_time=creation_time, gps=gps,
                           raw=raw or {})
    return _make

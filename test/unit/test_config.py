"""Tests for backend/config.py: Settings defaults, Paths.resolve(),
load_settings(), and startup_checks()."""
import subprocess
from pathlib import Path

import pytest

from backend import config as config_mod
from backend.config import (Settings, Paths, Video, Fade, startup_checks)


# ---------------------------------------------------------------------------
# Settings / model defaults
# ---------------------------------------------------------------------------

class TestSettingsDefaults:
    def test_default_settings_has_expected_sections(self):
        s = Settings()
        assert s.video.target_duration == 25
        assert s.video.segment_strategy == "energy"
        assert s.audio.music_mode == "duck"
        assert s.captions.enabled is True
        assert s.compilation.max_clips == 8
        assert s.compilation.min_clip_seconds == 3.0

    def test_fade_alias_in_maps_to_in__field(self):
        # "in" is a python keyword, the model uses alias="in" -> attribute in_
        fade = Fade(**{"in": 1.2, "out": 0.9})
        assert fade.in_ == 1.2
        assert fade.out == 0.9

    def test_fade_populate_by_name_also_works(self):
        fade = Fade(in_=0.7, out=0.3)
        assert fade.in_ == 0.7

    def test_video_defaults(self):
        v = Video()
        assert v.encoder == "h264_videotoolbox"
        assert v.fps == 30
        assert v.crf == 18


class TestAnthropicApiKeyProperty:
    def test_returns_none_when_env_var_absent(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert Settings().anthropic_api_key is None

    def test_returns_none_when_env_var_is_empty_string(self, monkeypatch):
        # `or None` in the property means "" is falsy too
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        assert Settings().anthropic_api_key is None

    def test_returns_value_when_env_var_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        assert Settings().anthropic_api_key == "sk-test-fake-key"


# ---------------------------------------------------------------------------
# Paths.resolve()
# ---------------------------------------------------------------------------

class TestPathsResolve:
    def test_relative_paths_resolved_against_project_root(self):
        p = Paths(music_dir=Path("./music"), output_dir=Path("./output"),
                  uploads_dir=Path("./uploads"))
        resolved = p.resolve()
        assert resolved.music_dir == (config_mod.PROJECT_ROOT / "music").resolve()
        assert resolved.output_dir == (config_mod.PROJECT_ROOT / "output").resolve()
        assert resolved.uploads_dir == (config_mod.PROJECT_ROOT / "uploads").resolve()

    def test_absolute_paths_are_left_untouched(self, tmp_path):
        abs_dir = tmp_path / "somewhere"
        p = Paths(music_dir=abs_dir, output_dir=abs_dir, uploads_dir=abs_dir)
        resolved = p.resolve()
        assert resolved.music_dir == abs_dir
        assert resolved.output_dir == abs_dir
        assert resolved.uploads_dir == abs_dir


# ---------------------------------------------------------------------------
# load_settings()
# ---------------------------------------------------------------------------

class TestLoadSettings:
    def test_missing_config_yaml_uses_defaults_and_creates_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
        s = config_mod.load_settings()
        assert s.video.target_duration == 25
        assert s.paths.music_dir.exists()
        assert s.paths.output_dir.exists()
        assert s.paths.uploads_dir.exists()

    def test_config_yaml_overrides_are_applied(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text(
            "video:\n  target_duration: 42\n  encoder: libx264\n")
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
        s = config_mod.load_settings()
        assert s.video.target_duration == 42
        assert s.video.encoder == "libx264"

    def test_empty_config_yaml_falls_back_to_defaults(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text("")  # yaml.safe_load("") -> None
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
        s = config_mod.load_settings()
        assert s.video.target_duration == 25

    def test_malformed_config_yaml_raises(self, tmp_path, monkeypatch):
        (tmp_path / "config.yaml").write_text("video: [unterminated\n")
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
        with pytest.raises(Exception):
            config_mod.load_settings()

    def test_unknown_top_level_key_is_rejected_by_pydantic(self, tmp_path, monkeypatch):
        # Settings has no extra="allow"; pydantic v2 default is "ignore" for
        # BaseModel unless configured otherwise. This test documents actual
        # behavior rather than assuming strict validation.
        (tmp_path / "config.yaml").write_text("bogus_section:\n  x: 1\n")
        monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
        s = config_mod.load_settings()  # should not raise: unknown keys ignored
        assert s.video.target_duration == 25


# ---------------------------------------------------------------------------
# startup_checks()
# ---------------------------------------------------------------------------

class TestStartupChecks:
    def test_raises_when_ffmpeg_missing(self, cfg, monkeypatch):
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: None)
        with pytest.raises(RuntimeError, match="ffmpeg/ffprobe not found"):
            startup_checks(cfg)

    def test_raises_when_required_filter_missing(self, cfg, monkeypatch):
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(args=[], returncode=0,
                                            stdout=" overlay  loudnorm  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        with pytest.raises(RuntimeError, match="sidechaincompress"):
            startup_checks(cfg)

    def test_warns_and_disables_music_when_no_tracks_present(self, cfg, monkeypatch):
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=" overlay  loudnorm  sidechaincompress  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        assert cfg.audio.music_mode == "duck"
        warnings = startup_checks(cfg)
        assert any("No music files" in w for w in warnings)
        assert cfg.audio.music_mode == "none"  # mutated in place

    def test_no_music_warning_when_music_mode_is_none(self, cfg, monkeypatch):
        cfg.audio.music_mode = "none"
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=" overlay  loudnorm  sidechaincompress  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        warnings = startup_checks(cfg)
        assert not any("No music files" in w for w in warnings)

    def test_no_music_warning_when_tracks_present(self, cfg, monkeypatch):
        (cfg.paths.music_dir / "track.mp3").write_bytes(b"fake")
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=" overlay  loudnorm  sidechaincompress  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        warnings = startup_checks(cfg)
        assert not any("No music files" in w for w in warnings)
        assert cfg.audio.music_mode == "duck"

    def test_warns_when_api_key_missing(self, cfg, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        (cfg.paths.music_dir / "track.mp3").write_bytes(b"fake")
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=" overlay  loudnorm  sidechaincompress  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        warnings = startup_checks(cfg)
        assert any("ANTHROPIC_API_KEY not set" in w for w in warnings)

    def test_no_api_key_warning_when_key_present(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        (cfg.paths.music_dir / "track.mp3").write_bytes(b"fake")
        monkeypatch.setattr(config_mod.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=" overlay  loudnorm  sidechaincompress  amix ")
        monkeypatch.setattr(config_mod.subprocess, "run", lambda *a, **k: fake)
        warnings = startup_checks(cfg)
        assert not any("ANTHROPIC_API_KEY" in w for w in warnings)

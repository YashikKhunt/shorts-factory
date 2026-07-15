"""Tests for backend/pipeline/runner.py: single-clip orchestration."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.pipeline import runner as runner_mod


class TestSafeStem:
    @pytest.mark.parametrize("name, expected", [
        ("My Trip.mov", "My_Trip"),
        ("clip (1).mp4", "clip_1"),
        ("normal_name.mp4", "normal_name"),
        ("---.mp4", "---"),           # hyphens are allowed chars, kept as-is
        ("***.mp4", "clip"),          # only disallowed chars -> fallback
        ("", "clip"),
        ("✈️trip✈️.mp4", "trip"),      # unicode stripped, leaves ascii core
    ])
    def test_sanitizes_name(self, name, expected):
        assert runner_mod._safe_stem(name) == expected


def _fake_meta(**overrides):
    base = dict(titles=["T1", "T2", "T3"], hashtags=["#shorts", "#travel"],
               hook="Hook!", location_guess=None, transcript=None, fallback=False)
    base.update(overrides)
    return SimpleNamespace(**base)


class TestProcessVideo:
    def _patch_pipeline(self, monkeypatch, cfg, tmp_path, *,
                        has_audio=True, captions_enabled=True,
                        transcript_segments=None, music_mode="duck"):
        info = SimpleNamespace(duration=20.0, width=1080, height=1920,
                               has_audio=has_audio, gps=None,
                               creation_time=None)
        monkeypatch.setattr(runner_mod, "probe", lambda src: info)
        monkeypatch.setattr(runner_mod.segment, "select_segment",
                            lambda *a, **k: (0.0, 20.0))
        monkeypatch.setattr(runner_mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
        monkeypatch.setattr(runner_mod.transcribe, "transcribe",
                            lambda *a, **k: transcript_segments)

        frame1 = tmp_path / "work" / "frame_0.jpg"
        frame1.parent.mkdir(parents=True, exist_ok=True)
        frame1.write_bytes(b"fake")
        frame2 = tmp_path / "work" / "frame_1.jpg"
        frame2.write_bytes(b"fake")
        monkeypatch.setattr(runner_mod.frames, "extract_frames",
                            lambda *a, **k: [frame1, frame2])

        meta = _fake_meta(transcript="hi" if transcript_segments else None)
        monkeypatch.setattr(runner_mod.metadata_ai, "generate_metadata",
                            lambda *a, **k: meta)
        monkeypatch.setattr(runner_mod.captions, "build_hook_overlay",
                            lambda *a, **k: "hook-overlay")
        monkeypatch.setattr(runner_mod.captions, "build_caption_overlays",
                            lambda *a, **k: ["cap-overlay"])
        monkeypatch.setattr(runner_mod.render, "pick_music",
                            lambda music_dir: (tmp_path / "music" / "song.mp3")
                            if music_mode != "none" else None)
        monkeypatch.setattr(runner_mod.render, "build_command", lambda *a, **k: ["ffmpeg"])

        run_render_calls = []
        monkeypatch.setattr(runner_mod.render, "run_render",
                            lambda cmd, dur, cb=None: run_render_calls.append((cmd, dur)))
        cfg.captions.enabled = captions_enabled
        cfg.audio.music_mode = music_mode
        return info, run_render_calls

    def test_happy_path_returns_expected_result_shape(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path,
                            transcript_segments=[(0.0, 1.0, "hi")])
        src = tmp_path / "input" / "My Clip.mov"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        result = runner_mod.process_video(src, cfg)

        assert result["titles"] == ["T1", "T2", "T3"]
        assert result["hashtags"] == ["#shorts", "#travel"]
        assert result["hook"] == "Hook!"
        assert result["segment"] == {"start": 0.0, "duration": 20.0}
        assert result["source"]["name"] == "My Clip.mov"
        assert result["source"]["resolution"] == "1080x1920"
        assert result["music"] == "song.mp3"
        assert Path(result["video"]).name == "My_Clip_short.mp4"
        assert Path(result["thumbnail"]).exists()

    def test_metadata_json_and_txt_written_to_disk(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path)
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        result = runner_mod.process_video(src, cfg)

        out_dir = cfg.paths.output_dir / "clip"
        json_file = out_dir / "clip_metadata.json"
        txt_file = out_dir / "clip_metadata.txt"
        assert json_file.exists()
        assert txt_file.exists()
        assert json.loads(json_file.read_text())["hook"] == "Hook!"
        assert "TITLES" in txt_file.read_text()

    def test_work_dir_cleaned_up_after_processing(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path)
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        runner_mod.process_video(src, cfg)
        work_dir = cfg.paths.output_dir / "clip" / "work"
        assert not work_dir.exists()

    def test_no_audio_skips_transcription(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path, has_audio=False)
        transcribe_calls = []
        monkeypatch.setattr(runner_mod.transcribe, "transcribe",
                            lambda *a, **k: transcribe_calls.append(1))
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        result = runner_mod.process_video(src, cfg)
        assert transcribe_calls == []
        assert result["transcript"] is None

    def test_captions_disabled_skips_transcription(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path, captions_enabled=False)
        transcribe_calls = []
        monkeypatch.setattr(runner_mod.transcribe, "transcribe",
                            lambda *a, **k: transcribe_calls.append(1))
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        runner_mod.process_video(src, cfg)
        assert transcribe_calls == []

    def test_music_mode_none_results_in_no_music(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path, music_mode="none")
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        result = runner_mod.process_video(src, cfg)
        assert result["music"] is None

    def test_progress_and_stage_callbacks_invoked(self, cfg, tmp_path, monkeypatch):
        self._patch_pipeline(monkeypatch, cfg, tmp_path,
                            transcript_segments=[(0.0, 1.0, "hi")])
        src = tmp_path / "input" / "clip.mp4"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")

        stages = []
        runner_mod.process_video(src, cfg, on_stage=stages.append)
        assert stages == ["probing", "selecting", "transcribing", "analyzing",
                          "rendering", "writing_outputs"]


class TestHumanMetadata:
    def test_basic_fields_rendered(self):
        r = {"titles": ["A", "B"], "hashtags": ["#shorts"], "hook": "Wow",
            "location_guess": None, "transcript": None, "metadata_fallback": False}
        text = runner_mod._human_metadata(r)
        assert "1. A" in text
        assert "2. B" in text
        assert "#shorts" in text
        assert "Hook overlay: Wow" in text

    def test_location_included_when_present(self):
        r = {"titles": [], "hashtags": [], "hook": "h", "location_guess": "Paris",
            "transcript": None, "metadata_fallback": False}
        assert "Location: Paris" in runner_mod._human_metadata(r)

    def test_transcript_section_included_when_present(self):
        r = {"titles": [], "hashtags": [], "hook": "h", "location_guess": None,
            "transcript": "hello world", "metadata_fallback": False}
        text = runner_mod._human_metadata(r)
        assert "=== TRANSCRIPT ===" in text
        assert "hello world" in text

    def test_fallback_warning_included_when_flagged(self):
        r = {"titles": [], "hashtags": [], "hook": "h", "location_guess": None,
            "transcript": None, "metadata_fallback": True}
        assert "Offline fallback metadata" in runner_mod._human_metadata(r)

    def test_clips_section_included_for_compilations(self):
        r = {"titles": [], "hashtags": [], "hook": "h", "location_guess": None,
            "transcript": None, "metadata_fallback": False,
            "clips": [{"name": "a.mp4", "source_start": 1.0, "duration": 5.0,
                      "timeline_start": 0.0}]}
        text = runner_mod._human_metadata(r)
        assert "=== EDIT ===" in text
        assert "a.mp4" in text

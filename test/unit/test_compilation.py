"""Tests for backend/pipeline/compilation.py — the multi-clip compilation
feature ("combine several videos into one AI-edited Short"). This is the
most recently added pipeline stage, so it gets the deepest coverage here.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from backend.pipeline import compilation as comp_mod
from backend.pipeline.edit_ai import ClipCut


def _info(duration=10.0, has_audio=True, creation_time=None, gps=None,
         width=1080, height=1920):
    return SimpleNamespace(duration=duration, has_audio=has_audio,
                           creation_time=creation_time, gps=gps,
                           width=width, height=height)


def _meta(**overrides):
    base = dict(titles=["T1"], hashtags=["#shorts", "#travel"], hook="Hook!",
               location_guess=None, transcript=None, fallback=False)
    base.update(overrides)
    return SimpleNamespace(**base)


class _CompilationHarness:
    """Wires up all of compilation.py's collaborators with controllable fakes."""

    def __init__(self, monkeypatch, cfg, tmp_path):
        self.monkeypatch = monkeypatch
        self.cfg = cfg
        self.tmp_path = tmp_path
        self.probe_results: dict[str, SimpleNamespace] = {}
        self.transcripts: dict[str, list] = {}
        self.decide_edit_result = None
        self.metadata = _meta()
        self.frame_paths: dict[str, list[Path]] = {}
        self.norm_cmds = []
        self.final_cmd_calls = []
        self.run_render_calls = []
        self.music_mode = "duck"
        self._wire()

    def _wire(self):
        m = self.monkeypatch

        def fake_probe(src):
            return self.probe_results[str(src)]
        m.setattr(comp_mod, "probe", fake_probe)

        def fake_extract_frames(src, start, duration, out_dir):
            paths = self.frame_paths.get(str(src))
            if paths is None:
                out_dir.mkdir(parents=True, exist_ok=True)
                p = out_dir / "frame_0.jpg"
                p.write_bytes(b"fake")
                paths = [p]
            return paths
        m.setattr(comp_mod.frames, "extract_frames", fake_extract_frames)

        m.setattr(comp_mod.segment, "energy_curve", lambda *a, **k: None)
        m.setattr(comp_mod.segment, "candidate_windows", lambda *a, **k: [])

        def fake_transcribe(wav, cfg):
            return self.transcripts.get(str(wav))
        m.setattr(comp_mod.transcribe, "transcribe", fake_transcribe)
        m.setattr(comp_mod.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))

        def fake_decide_edit(evidence, target, cfg):
            if self.decide_edit_result is not None:
                return self.decide_edit_result
            # default: use every clip evenly
            n = len(evidence)
            each = target / n
            return ([ClipCut(index=ev.index, start=0.0, duration=each)
                    for ev in evidence], False)
        m.setattr(comp_mod.edit_ai, "decide_edit", fake_decide_edit)

        m.setattr(comp_mod.metadata_ai, "generate_metadata",
                 lambda *a, **k: self.metadata)
        m.setattr(comp_mod.captions, "build_hook_overlay",
                 lambda *a, **k: "hook-overlay")
        m.setattr(comp_mod.captions, "build_caption_overlays",
                 lambda *a, **k: ["cap-overlay"])

        def fake_pick_music(music_dir):
            return (self.tmp_path / "music" / "song.mp3") if self.music_mode != "none" else None
        m.setattr(comp_mod.render, "pick_music", fake_pick_music)
        m.setattr(comp_mod.render, "build_normalize_command",
                 lambda src, part, info, start, dur, cfg: self.norm_cmds.append(
                     (src, part, start, dur)) or ["ffmpeg", "-norm"])
        m.setattr(comp_mod.render, "write_concat_list",
                 lambda parts, out: out.write_text("concat") or out)
        m.setattr(comp_mod.render, "build_final_command",
                 lambda concat_list, out, total, overlays, music, cfg:
                 self.final_cmd_calls.append((total, overlays, music)) or ["ffmpeg", "-final"])
        m.setattr(comp_mod.render, "run_render",
                 lambda cmd, dur, cb=None: self.run_render_calls.append((cmd, dur)))

    def add_clip(self, src: Path, **info_kwargs):
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"fake")
        self.probe_results[str(src)] = _info(**info_kwargs)
        return src


@pytest.fixture
def harness(monkeypatch, cfg, tmp_path):
    return _CompilationHarness(monkeypatch, cfg, tmp_path)


class TestProcessCompilationHappyPath:
    def test_returns_expected_result_shape(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4", duration=10.0)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", duration=10.0)

        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")

        assert result["video"].endswith("testcomp_short.mp4")
        assert Path(result["thumbnail"]).exists() is False  # thumb mocked via subprocess.run stub
        assert result["titles"] == ["T1"]
        assert result["hook"] == "Hook!"
        assert result["edit_fallback"] is False
        assert result["source"]["name"] == "2 clips"
        assert len(result["clips"]) == 2
        assert result["clips"][0]["name"] == "a.mp4"
        assert result["clips"][1]["name"] == "b.mp4"

    def test_metadata_files_written_and_workdir_cleaned(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")

        out_dir = cfg.paths.output_dir / "testcomp"
        assert (out_dir / "testcomp_metadata.json").exists()
        assert (out_dir / "testcomp_metadata.txt").exists()
        assert json.loads((out_dir / "testcomp_metadata.json").read_text())["hook"] == "Hook!"
        assert not (out_dir / "work").exists()

    def test_render_pipeline_invoked_once_per_clip_plus_final_pass(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        c = harness.add_clip(tmp_path / "in" / "c.mp4")
        comp_mod.process_compilation([a, b, c], cfg, name="testcomp")
        assert len(harness.norm_cmds) == 3
        assert len(harness.final_cmd_calls) == 1
        # normalize passes + final pass = 4 total run_render invocations
        assert len(harness.run_render_calls) == 4

    def test_music_none_mode_passes_no_music_to_final_command(self, harness, cfg, tmp_path):
        harness.music_mode = "none"
        cfg.audio.music_mode = "none"
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        _, _, music = harness.final_cmd_calls[0]
        assert music is None

    def test_default_name_uses_timestamp_prefix(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        result = comp_mod.process_compilation([a, b], cfg)  # no explicit name
        assert "compilation_" in result["video"]


class TestClipOrdering:
    def test_sorted_by_creation_time_when_all_present(self, harness, cfg, tmp_path):
        # add out of chronological order: b is earlier than a
        a = harness.add_clip(tmp_path / "in" / "a.mp4",
                             creation_time="2024-06-02T00:00:00Z")
        b = harness.add_clip(tmp_path / "in" / "b.mp4",
                             creation_time="2024-06-01T00:00:00Z")
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        names = [c["name"] for c in result["clips"]]
        assert names == ["b.mp4", "a.mp4"]

    def test_falls_back_to_selection_order_when_any_creation_time_missing(
            self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4",
                             creation_time="2024-06-02T00:00:00Z")
        b = harness.add_clip(tmp_path / "in" / "b.mp4", creation_time=None)
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        names = [c["name"] for c in result["clips"]]
        assert names == ["a.mp4", "b.mp4"]  # selection order preserved

    def test_earliest_creation_time_surfaced_in_source(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4",
                             creation_time="2024-06-02T00:00:00Z")
        b = harness.add_clip(tmp_path / "in" / "b.mp4",
                             creation_time="2024-06-01T00:00:00Z")
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert result["source"]["creation_time"] == "2024-06-01T00:00:00Z"

    def test_gps_taken_from_first_clip_that_has_it(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4", gps=None)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", gps=(1.0, 2.0))
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert result["source"]["gps"] == (1.0, 2.0)


class TestCaptionsAndTranscriptRebasing:
    def test_captions_disabled_skips_transcription_entirely(self, harness, cfg, tmp_path):
        cfg.captions.enabled = False
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        transcribe_calls = []
        harness.monkeypatch.setattr(comp_mod.transcribe, "transcribe",
                                    lambda *a, **k: transcribe_calls.append(1))
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert transcribe_calls == []

    def test_clip_without_audio_is_not_transcribed(self, harness, cfg, tmp_path):
        cfg.captions.enabled = True
        a = harness.add_clip(tmp_path / "in" / "a.mp4", has_audio=False)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", has_audio=True)
        transcribed = []
        orig = harness.transcripts

        def fake_transcribe(wav, cfg):
            transcribed.append(str(wav))
            return None
        harness.monkeypatch.setattr(comp_mod.transcribe, "transcribe", fake_transcribe)
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert len(transcribed) == 1  # only clip_1 (b) gets transcribed

    def test_transcript_rebased_onto_compilation_timeline(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4", duration=10.0)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", duration=10.0)
        # clip 0 transcript at [2,4]; cut uses [0,5) of clip 0 -> offset 0
        # clip 1 transcript at [1,3]; cut uses [0,5) of clip 1 -> offset 5 (clip0 dur)
        work_dir = cfg.paths.output_dir / "testcomp" / "work"
        harness.transcripts = {
            str(work_dir / "clip_0" / "full.wav"): [(2.0, 4.0, "clip a speech")],
            str(work_dir / "clip_1" / "full.wav"): [(1.0, 3.0, "clip b speech")],
        }
        harness.decide_edit_result = (
            [ClipCut(index=0, start=0.0, duration=5.0),
             ClipCut(index=1, start=0.0, duration=5.0)], False)

        captured_merged = {}

        def fake_generate_metadata(frames, info, name, merged, cfg, extra_context=None):
            captured_merged["merged"] = merged
            return _meta()
        harness.monkeypatch.setattr(comp_mod.metadata_ai, "generate_metadata",
                                    fake_generate_metadata)

        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        merged = captured_merged["merged"]
        assert merged == [(2.0, 4.0, "clip a speech"), (6.0, 8.0, "clip b speech")]

    def test_transcript_sliver_at_cut_boundary_is_dropped(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4", duration=10.0)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", duration=10.0)
        # transcript segment [4.0, 6.0] but cut only uses [0, 4.9) of clip 0:
        # overlap = [4.0, 4.9] = 0.9s out of a 2.0s segment (45% overlap, but
        # < 0.5s absolute is NOT true here so let's make an actual sliver)
        work_dir = cfg.paths.output_dir / "testcomp" / "work"
        harness.transcripts = {
            str(work_dir / "clip_0" / "full.wav"):
                [(4.8, 6.8, "straddles the cut")],
            str(work_dir / "clip_1" / "full.wav"): [],
        }
        harness.decide_edit_result = (
            [ClipCut(index=0, start=0.0, duration=5.0),
             ClipCut(index=1, start=0.0, duration=5.0)], False)

        captured_merged = {}

        def fake_generate_metadata(frames, info, name, merged, cfg, extra_context=None):
            captured_merged["merged"] = merged
            return _meta()
        harness.monkeypatch.setattr(comp_mod.metadata_ai, "generate_metadata",
                                    fake_generate_metadata)
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        # overlap = [4.8, 5.0] = 0.2s; overlap/segment_len = 0.2/2.0 = 0.1 (<0.3)
        # AND overlap (0.2) < 0.5s -> sliver dropped entirely. An empty
        # `merged` list is passed to generate_metadata as None (`merged or None`).
        assert captured_merged["merged"] is None

    def test_no_transcript_anywhere_skips_caption_overlays(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4", has_audio=False)
        b = harness.add_clip(tmp_path / "in" / "b.mp4", has_audio=False)
        overlay_calls = []
        harness.monkeypatch.setattr(
            comp_mod.captions, "build_caption_overlays",
            lambda *a, **k: overlay_calls.append(1) or [])
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert overlay_calls == []

    def test_hook_disabled_skips_hook_overlay(self, harness, cfg, tmp_path):
        cfg.hook.enabled = False
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        hook_calls = []
        harness.monkeypatch.setattr(
            comp_mod.captions, "build_hook_overlay",
            lambda *a, **k: hook_calls.append(1) or "overlay")
        comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert hook_calls == []


class TestEditFallbackFlagPassthrough:
    def test_ai_fallback_flag_propagates_to_result(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        harness.decide_edit_result = (
            [ClipCut(index=0, start=0.0, duration=5.0),
             ClipCut(index=1, start=0.0, duration=5.0)], True)
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert result["edit_fallback"] is True

    def test_ai_success_flag_propagates_to_result(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        harness.decide_edit_result = (
            [ClipCut(index=0, start=0.0, duration=5.0),
             ClipCut(index=1, start=0.0, duration=5.0)], False)
        result = comp_mod.process_compilation([a, b], cfg, name="testcomp")
        assert result["edit_fallback"] is False


class TestProgressReporting:
    def test_on_stage_called_in_expected_order(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        stages = []
        comp_mod.process_compilation([a, b], cfg, on_stage=stages.append, name="testcomp")
        assert stages == ["probing", "analyzing_clips", "transcribing",
                          "deciding_edit", "analyzing", "rendering",
                          "writing_outputs"]

    def test_on_stage_skips_transcribing_when_captions_disabled(self, harness, cfg, tmp_path):
        cfg.captions.enabled = False
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        stages = []
        comp_mod.process_compilation([a, b], cfg, on_stage=stages.append, name="testcomp")
        assert "transcribing" not in stages

    def test_on_progress_called_with_increasing_values(self, harness, cfg, tmp_path):
        a = harness.add_clip(tmp_path / "in" / "a.mp4")
        b = harness.add_clip(tmp_path / "in" / "b.mp4")
        progress = []

        def fake_run_render(cmd, dur, cb=None):
            if cb:
                cb(50.0)
                cb(100.0)
        harness.monkeypatch.setattr(comp_mod.render, "run_render", fake_run_render)
        comp_mod.process_compilation([a, b], cfg, on_progress=progress.append, name="testcomp")
        assert len(progress) > 0
        assert all(0.0 <= p <= 100.0 for p in progress)


class TestParseCt:
    def test_none_returns_none(self):
        assert comp_mod._parse_ct(None) is None

    def test_invalid_string_returns_none(self):
        assert comp_mod._parse_ct("not-a-date") is None

    def test_z_suffix_treated_as_utc(self):
        dt = comp_mod._parse_ct("2024-01-01T00:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_naive_datetime_gets_utc_attached(self):
        dt = comp_mod._parse_ct("2024-01-01T00:00:00")
        assert dt is not None
        assert dt.tzinfo is not None

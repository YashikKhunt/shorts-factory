"""Tests for backend/pipeline/render.py (ffmpeg command building + execution)."""
import subprocess

import pytest

from backend.pipeline import render as render_mod
from backend.pipeline.captions import Overlay


class TestPickMusic:
    def test_returns_none_for_empty_dir(self, tmp_path):
        assert render_mod.pick_music(tmp_path) is None

    def test_ignores_unsupported_extensions(self, tmp_path):
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / "cover.png").write_bytes(b"x")
        assert render_mod.pick_music(tmp_path) is None

    def test_picks_from_supported_extensions_only(self, tmp_path, monkeypatch):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.wav").write_bytes(b"x")
        (tmp_path / "readme.txt").write_bytes(b"x")
        monkeypatch.setattr(render_mod.random, "choice", lambda seq: seq[0])
        picked = render_mod.pick_music(tmp_path)
        assert picked.suffix in (".mp3", ".wav")

    def test_extension_matching_is_case_insensitive(self, tmp_path, monkeypatch):
        (tmp_path / "track.MP3").write_bytes(b"x")
        monkeypatch.setattr(render_mod.random, "choice", lambda seq: seq[0])
        picked = render_mod.pick_music(tmp_path)
        assert picked is not None
        assert picked.name == "track.MP3"


class TestAspectFilters:
    def test_native_9x16_passes_through_with_plain_scale(self, probe_factory):
        info = probe_factory(width=1080, height=1920)
        assert render_mod._aspect_filters(info, "crop") == "scale=1080:1920"

    def test_crop_strategy_for_wide_video(self, probe_factory):
        info = probe_factory(width=1920, height=1080)
        result = render_mod._aspect_filters(info, "crop")
        assert "crop=1080:1920" in result
        assert "force_original_aspect_ratio=increase" in result

    def test_pad_strategy_for_wide_video(self, probe_factory):
        info = probe_factory(width=1920, height=1080)
        result = render_mod._aspect_filters(info, "pad")
        assert "pad=1080:1920" in result
        assert "force_original_aspect_ratio=decrease" in result


class TestVideoNormChain:
    def test_color_grade_disabled_omits_eq_filter(self, cfg, probe_factory):
        cfg.video.color_grade.enabled = False
        info = probe_factory(is_hdr=False)
        chain = render_mod._video_norm_chain(info, cfg)
        assert not any(c.startswith("eq=") for c in chain)

    def test_hdr_boosts_saturation(self, cfg, probe_factory):
        cfg.video.color_grade.enabled = True
        cfg.video.color_grade.saturation = 1.0
        sdr_chain = render_mod._video_norm_chain(probe_factory(is_hdr=False), cfg)
        hdr_chain = render_mod._video_norm_chain(probe_factory(is_hdr=True), cfg)
        sdr_eq = next(c for c in sdr_chain if c.startswith("eq="))
        hdr_eq = next(c for c in hdr_chain if c.startswith("eq="))
        assert "saturation=1.00" in sdr_eq
        assert "saturation=1.10" in hdr_eq

    def test_ends_with_pixel_format(self, cfg, probe_factory):
        chain = render_mod._video_norm_chain(probe_factory(), cfg)
        assert chain[-1] == "format=yuv420p"

    def test_starts_with_fps_filter(self, cfg, probe_factory):
        cfg.video.fps = 24
        chain = render_mod._video_norm_chain(probe_factory(), cfg)
        assert chain[0] == "fps=24"


class TestOverlayGraph:
    def test_no_overlays_returns_current_label_unchanged(self):
        graph, cur = render_mod._overlay_graph("v0", [])
        assert graph == []
        assert cur == "v0"

    def test_chains_multiple_overlays_in_order(self, tmp_path):
        overlays = [Overlay(path=tmp_path / "a.png", start=0.0, end=1.0, y=10),
                    Overlay(path=tmp_path / "b.png", start=1.0, end=2.0, y=20)]
        graph, cur = render_mod._overlay_graph("v0", overlays)
        assert len(graph) == 2
        assert "[v0][1:v]overlay" in graph[0]
        assert "[v1][2:v]overlay" in graph[1]
        assert cur == "v2"
        assert "between(t,0.00,1.00)" in graph[0]
        assert "between(t,1.00,2.00)" in graph[1]


class TestFadeStep:
    def test_fade_out_start_clamped_to_zero_for_short_clips(self, cfg):
        cfg.video.fade.out = 5.0
        result = render_mod._fade_step("v0", duration=2.0, cfg=cfg)
        assert "st=0.00" in result  # fade-out start clamped, not negative

    def test_fade_in_and_out_durations_applied(self, cfg):
        cfg.video.fade.in_ = 0.4
        cfg.video.fade.out = 0.5
        result = render_mod._fade_step("v0", duration=10.0, cfg=cfg)
        assert "fade=t=in:st=0:d=0.4" in result
        assert "fade=t=out:st=9.50:d=0.5" in result
        assert result.endswith("[vout]")


class TestAudioGraph:
    def test_duck_mode_builds_sidechain_and_amix(self, cfg):
        graph, extra = render_mod._audio_graph(True, music_idx=1, music_mode="duck",
                                               duration=10.0, cfg=cfg, silent_idx=2)
        joined = ";".join(graph)
        assert "sidechaincompress" in joined
        assert "amix=inputs=2" in joined
        assert extra == []

    def test_mix_mode_builds_plain_amix(self, cfg):
        graph, extra = render_mod._audio_graph(True, music_idx=1, music_mode="mix",
                                               duration=10.0, cfg=cfg, silent_idx=2)
        joined = ";".join(graph)
        assert "amix=inputs=2" in joined
        assert "sidechaincompress" not in joined

    def test_replace_mode_uses_music_only(self, cfg):
        graph, extra = render_mod._audio_graph(True, music_idx=1, music_mode="replace",
                                               duration=10.0, cfg=cfg, silent_idx=2)
        joined = ";".join(graph)
        assert "[mus]anull[aout]" in joined
        assert "amix" not in joined

    def test_no_music_but_has_audio_passes_through(self, cfg):
        graph, extra = render_mod._audio_graph(True, music_idx=None, music_mode="none",
                                               duration=10.0, cfg=cfg, silent_idx=1)
        joined = ";".join(graph)
        assert "[orig]anull[aout]" in joined
        assert extra == []

    def test_no_audio_no_music_generates_silent_track(self, cfg):
        graph, extra = render_mod._audio_graph(False, music_idx=None, music_mode="none",
                                               duration=5.0, cfg=cfg, silent_idx=3)
        assert "-f" in extra and "lavfi" in extra
        assert any("anullsrc" in e for e in extra)
        assert "[3:a]anull[aout]" in ";".join(graph)

    def test_no_audio_but_music_present_uses_music_only(self, cfg):
        graph, extra = render_mod._audio_graph(False, music_idx=1, music_mode="duck",
                                               duration=5.0, cfg=cfg, silent_idx=2)
        joined = ";".join(graph)
        assert "[mus]anull[aout]" in joined
        assert extra == []

    def test_loudnorm_false_passes_through_untouched(self, cfg):
        graph, _ = render_mod._audio_graph(True, music_idx=None, music_mode="none",
                                           duration=5.0, cfg=cfg, silent_idx=1,
                                           loudnorm=False)
        assert "[0:a]anull[orig]" in ";".join(graph)

    def test_loudnorm_true_applies_loudnorm_filter(self, cfg):
        graph, _ = render_mod._audio_graph(True, music_idx=None, music_mode="none",
                                           duration=5.0, cfg=cfg, silent_idx=1,
                                           loudnorm=True)
        assert "loudnorm=I=" in ";".join(graph)


class TestEncoderArgs:
    def test_libx264_uses_crf(self, cfg):
        cfg.video.encoder = "libx264"
        cfg.video.crf = 20
        args = render_mod._encoder_args(cfg)
        assert "-crf" in args and "20" in args
        assert "-c:v" in args and "libx264" in args

    def test_videotoolbox_uses_bitrate(self, cfg):
        cfg.video.encoder = "h264_videotoolbox"
        cfg.video.bitrate = "8M"
        args = render_mod._encoder_args(cfg)
        assert "-b:v" in args and "8M" in args


class TestBuildCommand:
    def test_includes_source_seek_and_duration(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=True)
        cmd = render_mod.build_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                       info, start=5.0, duration=15.0,
                                       overlays=[], music=None, cfg=cfg)
        assert "-ss" in cmd and "5.000" in cmd
        assert "-t" in cmd
        assert str(tmp_path / "out.mp4") in cmd

    def test_music_input_added_when_music_provided(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=True)
        music = tmp_path / "song.mp3"
        music.write_bytes(b"x")
        cmd = render_mod.build_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                       info, 0.0, 10.0, [], music, cfg)
        assert str(music) in cmd
        assert "-stream_loop" in cmd

    def test_no_music_omits_stream_loop(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=True)
        cmd = render_mod.build_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                       info, 0.0, 10.0, [], None, cfg)
        assert "-stream_loop" not in cmd

    def test_overlays_added_as_extra_inputs(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=True)
        overlays = [Overlay(path=tmp_path / "hook.png", start=0.0, end=1.0, y=5)]
        cmd = render_mod.build_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                       info, 0.0, 10.0, overlays, None, cfg)
        assert str(tmp_path / "hook.png") in cmd


class TestBuildNormalizeCommand:
    def test_no_audio_source_gets_silent_input(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=False)
        cmd = render_mod.build_normalize_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                                  info, 0.0, 5.0, cfg)
        assert any("anullsrc" in c for c in cmd)

    def test_with_audio_applies_loudnorm_and_resample(self, cfg, probe_factory, tmp_path):
        info = probe_factory(has_audio=True)
        cmd = render_mod.build_normalize_command(tmp_path / "src.mp4", tmp_path / "out.mp4",
                                                  info, 0.0, 5.0, cfg)
        filt = next(c for c in cmd if "filter_complex" != c and "loudnorm" in c)
        assert f"aresample={render_mod.MEZZ_SAMPLE_RATE}" in filt


class TestWriteConcatList:
    def test_writes_one_file_line_per_part(self, tmp_path):
        parts = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
        out = render_mod.write_concat_list(parts, tmp_path / "concat.txt")
        text = out.read_text()
        assert text.count("file '") == 2
        assert str(parts[0]) in text and str(parts[1]) in text

    def test_escapes_single_quotes_in_paths(self, tmp_path):
        tricky = tmp_path / "it's a clip.mp4"
        out = render_mod.write_concat_list([tricky], tmp_path / "concat.txt")
        text = out.read_text()
        assert "it'\\''s a clip.mp4" in text


class TestBuildFinalCommand:
    def test_uses_concat_demuxer(self, cfg, tmp_path):
        concat_list = tmp_path / "concat.txt"
        concat_list.write_text("file 'a.mp4'\n")
        cmd = render_mod.build_final_command(concat_list, tmp_path / "out.mp4", 20.0,
                                             [], None, cfg)
        assert "-f" in cmd and "concat" in cmd
        assert str(concat_list) in cmd

    def test_no_loudnorm_in_final_pass(self, cfg, tmp_path):
        concat_list = tmp_path / "concat.txt"
        concat_list.write_text("file 'a.mp4'\n")
        cmd = render_mod.build_final_command(concat_list, tmp_path / "out.mp4", 20.0,
                                             [], None, cfg)
        filt = next(c for c in cmd if "0:a" in c)
        assert "loudnorm" not in filt


class TestRunRender:
    def test_calls_progress_callback_with_percentage(self, monkeypatch):
        class FakeProc:
            stdout = ["out_time_us=5000000\n", "out_time_us=10000000\n"]
            stderr = None
            returncode = 0

            def wait(self):
                return None

        monkeypatch.setattr(render_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
        seen = []
        render_mod.run_render(["ffmpeg"], duration=10.0, on_progress=seen.append)
        assert seen == pytest.approx([50.0, 100.0])

    def test_progress_clamped_to_100(self, monkeypatch):
        class FakeProc:
            stdout = ["out_time_us=99000000\n"]
            stderr = None
            returncode = 0

            def wait(self):
                return None

        monkeypatch.setattr(render_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
        seen = []
        render_mod.run_render(["ffmpeg"], duration=10.0, on_progress=seen.append)
        assert seen == [100.0]

    def test_malformed_progress_line_is_ignored(self, monkeypatch):
        class FakeProc:
            stdout = ["out_time_us=not-a-number\n"]
            stderr = None
            returncode = 0

            def wait(self):
                return None

        monkeypatch.setattr(render_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
        seen = []
        render_mod.run_render(["ffmpeg"], duration=10.0, on_progress=seen.append)
        assert seen == []

    def test_nonzero_return_code_raises_with_stderr(self, monkeypatch):
        import io

        class FakeProc:
            stdout = []
            stderr = io.StringIO("ffmpeg exploded")
            returncode = 1

            def wait(self):
                return None

        monkeypatch.setattr(render_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
        with pytest.raises(RuntimeError, match="ffmpeg render failed"):
            render_mod.run_render(["ffmpeg"], duration=10.0)

    def test_works_without_progress_callback(self, monkeypatch):
        class FakeProc:
            stdout = ["out_time_us=5000000\n"]
            stderr = None
            returncode = 0

            def wait(self):
                return None

        monkeypatch.setattr(render_mod.subprocess, "Popen", lambda *a, **k: FakeProc())
        render_mod.run_render(["ffmpeg"], duration=10.0)  # should not raise

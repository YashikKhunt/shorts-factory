"""Tests for backend/pipeline/probe.py (ffprobe wrapper)."""
import json
import subprocess
from pathlib import Path

import pytest

from backend.pipeline import probe as probe_mod


def _ffprobe_json(streams, fmt_tags=None, duration="12.5"):
    return json.dumps({
        "format": {"duration": duration, "tags": fmt_tags or {}},
        "streams": streams,
    })


def _fake_run(stdout, returncode=0):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=returncode,
                                            stdout=stdout, stderr="boom" if returncode else "")
    return _run


class TestProbeHappyPath:
    def test_basic_video_with_audio(self, monkeypatch):
        streams = [
            {"codec_type": "video", "width": 1920, "height": 1080,
             "r_frame_rate": "30/1", "pix_fmt": "yuv420p"},
            {"codec_type": "audio"},
        ]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mp4"))
        assert result.width == 1920
        assert result.height == 1080
        assert result.fps == 30.0
        assert result.has_audio is True
        assert result.duration == 12.5
        assert result.is_hdr is False
        assert result.aspect == pytest.approx(1920 / 1080)

    def test_no_audio_stream(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 640, "height": 480,
                    "r_frame_rate": "25/1"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mp4"))
        assert result.has_audio is False


class TestProbeRotation:
    def test_rotation_90_swaps_dimensions_via_side_data(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1",
                   "side_data_list": [{"rotation": 90}]}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mov"))
        assert (result.width, result.height) == (1080, 1920)

    def test_rotation_270_also_swaps(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1",
                   "side_data_list": [{"rotation": -90}]}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mov"))
        assert (result.width, result.height) == (1080, 1920)

    def test_rotation_180_does_not_swap(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1",
                   "side_data_list": [{"rotation": 180}]}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mov"))
        assert (result.width, result.height) == (1920, 1080)

    def test_rotation_from_tags_when_no_side_data(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1", "tags": {"rotate": "90"}}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/video.mov"))
        assert (result.width, result.height) == (1080, 1920)


class TestProbeErrors:
    def test_ffprobe_nonzero_exit_raises(self, monkeypatch):
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run("", returncode=1))
        with pytest.raises(RuntimeError, match="Could not read video file"):
            probe_mod.probe(Path("/fake/missing.mp4"))

    def test_no_video_stream_raises(self, monkeypatch):
        streams = [{"codec_type": "audio"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        with pytest.raises(RuntimeError, match="no video stream"):
            probe_mod.probe(Path("/fake/audio_only.mp4"))


class TestProbeHdrDetection:
    def test_hdr_detected_when_10bit_and_bt2020(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 3840, "height": 2160,
                   "r_frame_rate": "30/1", "pix_fmt": "yuv420p10le",
                   "color_primaries": "bt2020", "color_space": "bt2020nc"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/hdr.mov"))
        assert result.is_hdr is True

    def test_not_hdr_when_10bit_but_not_bt2020(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 3840, "height": 2160,
                   "r_frame_rate": "30/1", "pix_fmt": "yuv420p10le",
                   "color_primaries": "bt709", "color_space": "bt709"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/not_hdr.mov"))
        assert result.is_hdr is False

    def test_not_hdr_when_8bit(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1", "pix_fmt": "yuv420p",
                   "color_primaries": "bt2020", "color_space": "bt2020nc"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/sdr.mov"))
        assert result.is_hdr is False


class TestProbeFpsParsing:
    def test_fractional_frame_rate(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30000/1001"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/ntsc.mp4"))
        assert result.fps == pytest.approx(29.97, abs=0.01)

    def test_zero_denominator_falls_back_to_30(self, monkeypatch):
        # Guards the division-by-zero branch in probe(): "25/0" -> fps=30.0
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "25/0"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/weird.mp4"))
        assert result.fps == 30.0

    def test_missing_r_frame_rate_defaults_to_30(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/no_rate.mp4"))
        assert result.fps == 30.0


class TestProbeGpsAndCreationTime:
    def test_gps_parsed_from_iso6709(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1",
                   "tags": {"com.apple.quicktime.location.ISO6709": "+40.7128-074.0060/"}}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/gps.mov"))
        assert result.gps == (40.7128, -74.006)

    def test_gps_none_when_absent(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1"}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/no_gps.mov"))
        assert result.gps is None

    def test_creation_time_prefers_standard_tag(self, monkeypatch):
        streams = [{"codec_type": "video", "width": 1920, "height": 1080,
                   "r_frame_rate": "30/1",
                   "tags": {"creation_time": "2024-01-01T00:00:00Z"}}]
        monkeypatch.setattr(probe_mod.subprocess, "run",
                            _fake_run(_ffprobe_json(streams)))
        result = probe_mod.probe(Path("/fake/dated.mov"))
        assert result.creation_time == "2024-01-01T00:00:00Z"


class TestAspectProperty:
    def test_aspect_ratio_computed(self, probe_factory):
        p = probe_factory(width=1080, height=1920)
        assert p.aspect == pytest.approx(1080 / 1920)

    def test_aspect_defaults_to_1_when_height_zero(self, probe_factory):
        p = probe_factory(width=100, height=0)
        assert p.aspect == 1.0


class TestParseIso6709Helper:
    @pytest.mark.parametrize("raw, expected", [
        ("+40.7128-074.0060/", (40.7128, -74.006)),
        ("-33.8688+151.2093/", (-33.8688, 151.2093)),
    ])
    def test_valid_strings(self, raw, expected):
        assert probe_mod._parse_iso6709(raw) == expected

    def test_garbage_string_returns_none(self):
        assert probe_mod._parse_iso6709("not-a-coordinate") is None

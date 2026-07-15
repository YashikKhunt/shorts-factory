"""Tests for backend/pipeline/frames.py (representative frame extraction)."""
import subprocess

import pytest

from backend.pipeline import frames as frames_mod


def _mock_run_success(out_dir):
    """ffmpeg mock that actually creates the requested -q:v output file."""
    def _run(cmd, capture_output=True, text=True):
        out_path = cmd[-1]
        with open(out_path, "wb") as f:
            f.write(b"fake-jpeg-bytes")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
    return _run


class TestExtractFrames:
    def test_extracts_one_frame_per_fraction(self, tmp_path, monkeypatch):
        monkeypatch.setattr(frames_mod.subprocess, "run", _mock_run_success(tmp_path))
        result = frames_mod.extract_frames(tmp_path / "src.mp4", 0.0, 20.0, tmp_path / "out")
        assert len(result) == len(frames_mod.FRACTIONS)
        for p in result:
            assert p.exists()

    def test_out_dir_created_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(frames_mod.subprocess, "run", _mock_run_success(tmp_path))
        out_dir = tmp_path / "nested" / "out"
        assert not out_dir.exists()
        frames_mod.extract_frames(tmp_path / "src.mp4", 0.0, 20.0, out_dir)
        assert out_dir.exists()

    def test_partial_failures_still_return_successful_frames(self, tmp_path, monkeypatch):
        calls = {"n": 0}

        def _run(cmd, capture_output=True, text=True):
            calls["n"] += 1
            out_path = cmd[-1]
            if calls["n"] == 2:  # fail the middle frame
                return subprocess.CompletedProcess(args=cmd, returncode=1,
                                                    stdout="", stderr="decode error")
            with open(out_path, "wb") as f:
                f.write(b"fake")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(frames_mod.subprocess, "run", _run)
        result = frames_mod.extract_frames(tmp_path / "src.mp4", 0.0, 20.0, tmp_path / "out")
        assert len(result) == len(frames_mod.FRACTIONS) - 1

    def test_all_failures_raises(self, tmp_path, monkeypatch):
        def _run(cmd, capture_output=True, text=True):
            return subprocess.CompletedProcess(args=cmd, returncode=1,
                                                stdout="", stderr="decode error")
        monkeypatch.setattr(frames_mod.subprocess, "run", _run)
        with pytest.raises(RuntimeError, match="Could not extract any frames"):
            frames_mod.extract_frames(tmp_path / "src.mp4", 0.0, 20.0, tmp_path / "out")

    def test_frame_times_computed_from_start_and_fraction(self, tmp_path, monkeypatch):
        seen_times = []

        def _run(cmd, capture_output=True, text=True):
            ss_idx = cmd.index("-ss") + 1
            seen_times.append(float(cmd[ss_idx]))
            out_path = cmd[-1]
            with open(out_path, "wb") as f:
                f.write(b"fake")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(frames_mod.subprocess, "run", _run)
        frames_mod.extract_frames(tmp_path / "src.mp4", 10.0, 20.0, tmp_path / "out")
        expected = [10.0 + 20.0 * f for f in frames_mod.FRACTIONS]
        assert seen_times == pytest.approx(expected)

    def test_zero_duration_still_produces_frame_requests(self, tmp_path, monkeypatch):
        # boundary: duration=0 means every fraction maps to the same timestamp
        monkeypatch.setattr(frames_mod.subprocess, "run", _mock_run_success(tmp_path))
        result = frames_mod.extract_frames(tmp_path / "src.mp4", 5.0, 0.0, tmp_path / "out")
        assert len(result) == len(frames_mod.FRACTIONS)

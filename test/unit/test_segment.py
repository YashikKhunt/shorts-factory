"""Tests for backend/pipeline/segment.py (energy-based segment selection)."""
import subprocess

import numpy as np
import pytest

from backend.pipeline import segment as segment_mod


def _pcm_bytes_from_rms(levels: list[float], hop_samples: int) -> bytes:
    """Build int16 PCM where each `hop_samples`-sample block has ~the given RMS."""
    chunks = []
    for lvl in levels:
        amp = int(lvl * 32767)
        block = np.full(hop_samples, amp, dtype=np.int16)
        chunks.append(block)
    return np.concatenate(chunks).tobytes()


class TestEnergyCurve:
    def test_returns_none_when_no_audio(self, probe_factory):
        info = probe_factory(has_audio=False)
        assert segment_mod.energy_curve("irrelevant", info) is None

    def test_returns_none_on_ffmpeg_failure(self, probe_factory, monkeypatch):
        info = probe_factory(has_audio=True)
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout=b"")
        monkeypatch.setattr(segment_mod.subprocess, "run", lambda *a, **k: fake)
        assert segment_mod.energy_curve("path", info) is None

    def test_returns_none_when_output_too_short(self, probe_factory, monkeypatch):
        info = probe_factory(has_audio=True)
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=b"\x00\x01")
        monkeypatch.setattr(segment_mod.subprocess, "run", lambda *a, **k: fake)
        assert segment_mod.energy_curve("path", info) is None

    def test_computes_rms_per_window(self, probe_factory, monkeypatch):
        info = probe_factory(has_audio=True)
        hop = int(segment_mod.WINDOW_S * segment_mod.SAMPLE_RATE)
        pcm = _pcm_bytes_from_rms([0.5, 1.0, 0.25], hop)
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=pcm)
        monkeypatch.setattr(segment_mod.subprocess, "run", lambda *a, **k: fake)
        rms = segment_mod.energy_curve("path", info)
        assert rms is not None
        assert len(rms) == 3
        assert rms[1] > rms[0] > rms[2]


class TestCandidateWindows:
    def test_returns_empty_for_empty_input(self):
        assert segment_mod.candidate_windows(np.array([]), window_s=1.0) == []

    def test_window_covers_entire_curve_returns_single_mean(self):
        rms = np.array([1.0, 2.0, 3.0, 4.0])
        # window_s / WINDOW_S(0.5) = win >= n(4) -> whole-curve mean
        result = segment_mod.candidate_windows(rms, window_s=4.0)
        assert result == [(0.0, pytest.approx(2.5))]

    def test_picks_highest_energy_window_first(self):
        # 10 buckets of 0.5s; energy spikes around bucket 6-7
        rms = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, 5.0, 0.0, 0.0])
        wins = segment_mod.candidate_windows(rms, window_s=1.0, k=1)
        assert len(wins) == 1
        start, score = wins[0]
        assert start == pytest.approx(3.0)  # bucket index 6 * 0.5s
        assert score == pytest.approx(5.0)

    def test_non_overlapping_top_k_windows(self):
        rms = np.array([5.0, 5.0, 0.0, 0.0, 4.0, 4.0, 0.0, 0.0])
        wins = segment_mod.candidate_windows(rms, window_s=1.0, k=2)
        assert len(wins) == 2
        starts = sorted(s for s, _ in wins)
        assert starts == [0.0, pytest.approx(2.0)]

    def test_stops_early_when_scores_exhausted(self):
        rms = np.array([1.0, 1.0])
        wins = segment_mod.candidate_windows(rms, window_s=1.0, k=5)
        assert len(wins) <= 2  # never returns more windows than fit


class TestSelectSegment:
    def test_short_clip_returns_whole_clip(self, probe_factory):
        info = probe_factory(duration=10.0)
        start, dur = segment_mod.select_segment("p", info, target=25.0)
        assert (start, dur) == (0.0, 10.0)

    def test_non_energy_strategy_returns_start_of_clip(self, probe_factory):
        info = probe_factory(duration=60.0, has_audio=True)
        start, dur = segment_mod.select_segment("p", info, target=20.0, strategy="first")
        assert (start, dur) == (0.0, 20.0)

    def test_no_audio_falls_back_to_start(self, probe_factory):
        info = probe_factory(duration=60.0, has_audio=False)
        start, dur = segment_mod.select_segment("p", info, target=20.0, strategy="energy")
        assert (start, dur) == (0.0, 20.0)

    def test_energy_curve_none_falls_back_to_start(self, probe_factory, monkeypatch):
        info = probe_factory(duration=60.0, has_audio=True)
        monkeypatch.setattr(segment_mod, "energy_curve", lambda *a, **k: None)
        start, dur = segment_mod.select_segment("p", info, target=20.0, strategy="energy")
        assert (start, dur) == (0.0, 20.0)

    def test_energy_strategy_picks_best_window(self, probe_factory, monkeypatch):
        info = probe_factory(duration=60.0, has_audio=True)
        fake_rms = np.zeros(120)  # 60s / 0.5s window
        monkeypatch.setattr(segment_mod, "energy_curve", lambda *a, **k: fake_rms)
        monkeypatch.setattr(segment_mod, "candidate_windows",
                            lambda rms, target, k=1: [(15.0, 9.9)])
        start, dur = segment_mod.select_segment("p", info, target=20.0, strategy="energy")
        assert (start, dur) == (15.0, 20.0)

    def test_energy_window_clamped_to_not_exceed_clip_end(self, probe_factory, monkeypatch):
        info = probe_factory(duration=60.0, has_audio=True)
        fake_rms = np.zeros(120)
        monkeypatch.setattr(segment_mod, "energy_curve", lambda *a, **k: fake_rms)
        # candidate window starts near the end -- must clamp to duration - target
        monkeypatch.setattr(segment_mod, "candidate_windows",
                            lambda rms, target, k=1: [(55.0, 9.9)])
        start, dur = segment_mod.select_segment("p", info, target=20.0, strategy="energy")
        assert start == pytest.approx(40.0)  # 60 - 20
        assert dur == 20.0

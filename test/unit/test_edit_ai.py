"""Tests for backend/pipeline/edit_ai.py: the compilation edit-decision engine.

Covers the deterministic `fallback_edit`, the strict `_validate` EDL
validator, and `decide_edit`'s AI/fallback branching. `anthropic.Anthropic`
is always mocked — no real network calls.
"""
from types import SimpleNamespace

import anthropic
import numpy as np
import pytest

from backend.pipeline import edit_ai


def _evidence(index, duration, energy=None, transcript=None, name=None):
    return edit_ai.ClipEvidence(
        index=index, name=name or f"clip{index}.mp4",
        info=SimpleNamespace(duration=duration, creation_time=None, has_audio=True),
        frames=[], frame_times=[], energy=energy, candidates=[], transcript=transcript)


def _fake_client(parsed_output=None, text_fallback=None):
    response = SimpleNamespace(
        parsed_output=parsed_output,
        content=[SimpleNamespace(type="text", text=text_fallback)] if text_fallback else [],
    )

    class FakeMessages:
        def parse(self, **kwargs):
            return response

    return SimpleNamespace(messages=FakeMessages())


class TestFallbackEdit:
    def test_two_equal_length_clips_split_target_evenly(self):
        evidence = [_evidence(0, duration=30.0), _evidence(1, duration=30.0)]
        cuts = edit_ai.fallback_edit(evidence, target=20.0, min_clip=3.0)
        assert len(cuts) == 2
        assert sum(c.duration for c in cuts) == pytest.approx(20.0, abs=0.1)
        assert cuts[0].duration == pytest.approx(cuts[1].duration, abs=0.1)

    def test_short_clip_takes_its_whole_length(self):
        evidence = [_evidence(0, duration=2.0), _evidence(1, duration=30.0)]
        cuts = edit_ai.fallback_edit(evidence, target=20.0, min_clip=3.0)
        by_index = {c.index: c for c in cuts}
        # clip 0 is shorter than min_clip -> gets its whole duration
        assert by_index[0].duration == pytest.approx(2.0)
        # remaining clip absorbs the rest of the target
        assert by_index[1].duration == pytest.approx(18.0, abs=0.5)

    def test_cuts_emitted_in_evidence_order_not_allocation_order(self):
        # allocation processes shortest-first internally, but cuts must come
        # back in the same order as `evidence` (chronological clip order)
        evidence = [_evidence(0, duration=30.0), _evidence(1, duration=5.0),
                   _evidence(2, duration=30.0)]
        cuts = edit_ai.fallback_edit(evidence, target=20.0, min_clip=3.0)
        assert [c.index for c in cuts] == [0, 1, 2]

    def test_uses_energy_peak_as_window_start_when_available(self):
        rms = np.zeros(60)  # 30s of 0.5s buckets
        rms[10] = 5.0  # peak at t=5.0s
        evidence = [_evidence(0, duration=30.0, energy=rms)]
        cuts = edit_ai.fallback_edit(evidence, target=10.0, min_clip=3.0)
        # single clip: allotted = target = 10s (clamped to clip duration)
        assert cuts[0].duration == pytest.approx(10.0)

    def test_no_energy_centers_the_window(self):
        evidence = [_evidence(0, duration=30.0, energy=None)]
        cuts = edit_ai.fallback_edit(evidence, target=10.0, min_clip=3.0)
        assert cuts[0].start == pytest.approx((30.0 - 10.0) / 2)

    def test_single_clip_shorter_than_min_clip_still_returns_full_clip(self):
        evidence = [_evidence(0, duration=1.5)]
        cuts = edit_ai.fallback_edit(evidence, target=10.0, min_clip=3.0)
        assert cuts[0].duration == pytest.approx(1.5)
        assert cuts[0].start == 0.0


class TestValidate:
    def _evidence_pair(self, d0=20.0, d1=20.0):
        return [_evidence(0, duration=d0), _evidence(1, duration=d1)]

    def test_valid_edl_accepted(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": 2.0, "duration": 10.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None
        assert [c.index for c in cuts] == [0, 1]
        assert cuts[0].start == 2.0 and cuts[0].duration == 10.0

    def test_unknown_clip_index_skipped(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 99, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 0, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None
        assert len(cuts) == 2

    def test_use_false_is_skipped(self):
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0),
                   _evidence(2, duration=20.0)]
        raw = {"clips": [
            {"index": 0, "use": False, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 2, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None
        assert [c.index for c in cuts] == [1, 2]

    def test_duplicate_index_only_counted_once(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 0, "use": True, "start": 5.0, "duration": 10.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        # only 1 unique used clip < min(2, len(evidence)) -> invalid
        assert cuts is None

    def test_non_numeric_start_returns_none(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": "not-a-number", "duration": 10.0, "reason": "r"},
        ]}
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_missing_duration_key_returns_none(self):
        evidence = self._evidence_pair()
        raw = {"clips": [{"index": 0, "use": True, "start": 0.0, "reason": "r"}]}
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_negative_start_returns_none(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": -1.0, "duration": 10.0, "reason": "r"},
        ]}
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_zero_or_negative_duration_returns_none(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 0.0, "reason": "r"},
        ]}
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_nan_values_rejected(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 0, "use": True, "start": float("nan"), "duration": 10.0, "reason": "r"},
        ]}
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_too_few_clips_used_returns_none(self):
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0),
                   _evidence(2, duration=20.0)]
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 20.0, "reason": "r"},
        ]}
        # min(2, 3) == 2 required, only 1 given
        assert edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0) is None

    def test_single_clip_evidence_only_needs_one_used_clip(self):
        evidence = [_evidence(0, duration=20.0)]
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 20.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None and len(cuts) == 1

    def test_total_far_from_target_is_scaled(self):
        evidence = self._evidence_pair(d0=40.0, d1=40.0)
        # total requested = 60, target = 20 -> ratio way off, triggers scaling
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 30.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 30.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None
        total = sum(c.duration for c in cuts)
        assert total <= 25.0  # scaled down close to target, or rejected by the +5 cap

    def test_total_still_over_cap_after_scale_returns_none(self):
        # construct a case where per-clip min_clip floors prevent scaling
        # down enough, exceeding target + 5 even after the rescale pass
        evidence = [_evidence(0, duration=100.0), _evidence(1, duration=100.0)]
        raw = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 90.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 90.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=5.0, min_clip=50.0)
        assert cuts is None

    def test_result_ordered_chronologically_regardless_of_input_order(self):
        evidence = self._evidence_pair()
        raw = {"clips": [
            {"index": 1, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 0, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
        ]}
        cuts = edit_ai._validate(raw, evidence, target=20.0, min_clip=3.0)
        assert cuts is not None
        assert [c.index for c in cuts] == [0, 1]


class TestDecideEdit:
    def test_no_api_key_uses_fallback(self, cfg):
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is True
        assert len(cuts) == 2

    def test_valid_ai_response_used_when_key_present(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        data = {"clips": [
            {"index": 0, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
            {"index": 1, "use": True, "start": 0.0, "duration": 10.0, "reason": "r"},
        ]}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is False
        assert len(cuts) == 2

    def test_ai_garbage_falls_back(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        data = {"clips": [
            {"index": 0, "use": True, "start": -5.0, "duration": 10.0, "reason": "r"},
        ]}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is True
        assert len(cuts) == 2

    def test_api_status_error_falls_back(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

        class RaisingMessages:
            def parse(self, **kwargs):
                raise anthropic.APIStatusError(
                    "boom", response=SimpleNamespace(status_code=500,
                                                     headers={}, request=None),
                    body=None)

        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: SimpleNamespace(messages=RaisingMessages()))
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is True

    def test_connection_error_falls_back(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

        class RaisingMessages:
            def parse(self, **kwargs):
                raise anthropic.APIConnectionError(request=SimpleNamespace())

        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: SimpleNamespace(messages=RaisingMessages()))
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is True

    def test_unparseable_json_text_fallback_falls_back(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: _fake_client(parsed_output=None,
                                                 text_fallback="not json at all"))
        evidence = [_evidence(0, duration=20.0), _evidence(1, duration=20.0)]
        cuts, used_fallback = edit_ai.decide_edit(evidence, target=20.0, cfg=cfg)
        assert used_fallback is True

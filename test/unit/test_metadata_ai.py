"""Tests for backend/pipeline/metadata_ai.py (Claude-generated titles/hashtags).

IMPORTANT: `anthropic.Anthropic` is always mocked. This suite must never
perform a real network call, even though a real ANTHROPIC_API_KEY exists in
this dev machine's .env — the autouse `_no_real_api_key` fixture strips it
from the environment by default, and tests that opt back in always replace
`anthropic.Anthropic` with a fake client first.
"""
from types import SimpleNamespace

import anthropic
import pytest

from backend.pipeline import metadata_ai as meta_mod


def _fake_client(parsed_output=None, text_fallback=None, usage=(10, 20)):
    """Build a fake anthropic.Anthropic()-like object with .messages.parse()."""
    response = SimpleNamespace(
        parsed_output=parsed_output,
        content=[SimpleNamespace(type="text", text=text_fallback)] if text_fallback else [],
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )

    class FakeMessages:
        def parse(self, **kwargs):
            return response

    return SimpleNamespace(messages=FakeMessages())


class TestCfgKeyPresent:
    def test_false_when_no_key(self, cfg):
        assert meta_mod.cfg_key_present(cfg) is False

    def test_true_when_key_set(self, cfg, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        assert meta_mod.cfg_key_present(cfg) is True


class TestGenerateMetadataOfflineFallback:
    def test_no_api_key_uses_fallback(self, cfg, probe_factory, tmp_path):
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "my_trip_video.mp4", None, cfg)
        assert meta.fallback is True
        assert meta.hook == cfg.hook.fallback_text
        assert meta.hashtags[:2] == ["#shorts", "#travel"]
        assert any("My Trip Video" in t for t in meta.titles)

    def test_fallback_includes_transcript_when_present(self, cfg, probe_factory):
        info = probe_factory()
        segments = [(0.0, 1.0, "hello"), (1.0, 2.0, "world")]
        meta = meta_mod.generate_metadata([], info, "clip.mp4", segments, cfg)
        assert meta.transcript == "hello world"

    def test_fallback_hashtags_include_configured_broad_tags(self, cfg, probe_factory):
        cfg.hashtags.broad = ["#shorts", "#travel", "#custom"]
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert "#custom" in meta.hashtags
        # no duplicates even though #shorts/#travel appear in both the
        # hard-coded prefix and cfg.hashtags.broad
        assert len(meta.hashtags) == len(set(meta.hashtags))

    def test_fallback_stem_replaces_separators_and_title_cases(self, cfg, probe_factory):
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "sunset-at_the-beach.mov", None, cfg)
        assert any("Sunset At The Beach" in t for t in meta.titles)


class TestGenerateMetadataWithAi:
    def test_successful_ai_response_parsed(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        data = {"titles": ["T1", "T2", "T3"], "hashtags": ["#shorts", "#travel"],
                "hook": "Wow look!", "location_guess": "Bali"}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.fallback is False
        assert meta.titles == ["T1", "T2", "T3"]
        assert meta.hook == "Wow look!"
        assert meta.location_guess == "Bali"
        assert meta.extra["usage"] == {"input": 10, "output": 20}

    def test_titles_truncated_to_configured_count(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        cfg.claude.title_count = 2
        data = {"titles": ["T1", "T2", "T3", "T4"], "hashtags": ["#shorts"],
                "hook": "hook", "location_guess": None}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.titles == ["T1", "T2"]

    def test_falls_back_to_text_content_when_parsed_output_is_none(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        raw_json = ('{"titles": ["T1"], "hashtags": ["#shorts"], '
                   '"hook": "hi", "location_guess": null}')
        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: _fake_client(parsed_output=None, text_fallback=raw_json))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.titles == ["T1"]
        assert meta.fallback is False

    def test_api_status_error_falls_back(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

        class RaisingMessages:
            def parse(self, **kwargs):
                raise anthropic.APIStatusError(
                    "boom", response=SimpleNamespace(status_code=500,
                                                     headers={}, request=None),
                    body=None)

        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: SimpleNamespace(messages=RaisingMessages()))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.fallback is True

    def test_connection_error_falls_back(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")

        class RaisingMessages:
            def parse(self, **kwargs):
                raise anthropic.APIConnectionError(request=SimpleNamespace())

        monkeypatch.setattr(anthropic, "Anthropic",
                            lambda: SimpleNamespace(messages=RaisingMessages()))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.fallback is True

    def test_garbage_response_shape_falls_back(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        # missing required "hook" key -> KeyError when building VideoMetadata
        data = {"titles": ["T1"], "hashtags": ["#shorts"], "location_guess": None}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        info = probe_factory()
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg)
        assert meta.fallback is True

    def test_extra_context_lines_do_not_raise(self, cfg, probe_factory, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key")
        data = {"titles": ["T1"], "hashtags": ["#shorts"], "hook": "hi",
                "location_guess": None}
        monkeypatch.setattr(anthropic, "Anthropic", lambda: _fake_client(parsed_output=data))
        info = probe_factory(gps=(1.0, 2.0), creation_time="2024-01-01T00:00:00Z")
        meta = meta_mod.generate_metadata([], info, "clip.mp4", None, cfg,
                                          extra_context=["extra line one"])
        assert meta.fallback is False

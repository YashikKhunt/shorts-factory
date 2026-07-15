"""Tests for backend/scripts/process_one.py (dev CLI harness)."""
import json

import pytest

from backend.scripts import process_one


class TestArgParsing:
    def test_no_args_exits_with_usage(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["process_one"])
        with pytest.raises(SystemExit) as exc:
            process_one.main()
        assert "usage" in str(exc.value)

    def test_combine_flag_stripped_from_args_but_requires_two_files(
            self, monkeypatch, tmp_path, cfg_factory, capsys):
        # --combine with only 1 file falls through to the single-file loop
        only_file = tmp_path / "a.mp4"
        only_file.write_bytes(b"x")
        monkeypatch.setattr("sys.argv", ["process_one", "--combine", str(only_file)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: [])

        calls = []
        monkeypatch.setattr(process_one, "process_video",
                            lambda src, cfg, on_stage, on_progress: calls.append(("single", src))
                            or {"video": "out.mp4", "titles": [], "hashtags": [],
                                "hook": "h", "metadata_fallback": False})
        process_one.main()
        assert calls == [("single", only_file.resolve())]


class TestCombineMode:
    def test_missing_file_in_combine_mode_exits(self, monkeypatch, tmp_path, cfg_factory):
        existing = tmp_path / "exists.mp4"
        existing.write_bytes(b"x")
        missing = tmp_path / "missing.mp4"
        monkeypatch.setattr("sys.argv",
                            ["process_one", "--combine", str(existing), str(missing)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: [])
        with pytest.raises(SystemExit) as exc:
            process_one.main()
        assert "not found" in str(exc.value)
        assert "missing.mp4" in str(exc.value)

    def test_combine_with_two_files_calls_process_compilation(
            self, monkeypatch, tmp_path, cfg_factory, capsys):
        a = tmp_path / "a.mp4"
        a.write_bytes(b"x")
        b = tmp_path / "b.mp4"
        b.write_bytes(b"x")
        monkeypatch.setattr("sys.argv", ["process_one", "--combine", str(a), str(b)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: [])

        calls = []

        def fake_compilation(srcs, cfg, on_stage, on_progress):
            calls.append(srcs)
            return {"video": "combo.mp4", "titles": ["T1"], "hook": "h",
                   "clips": [], "edit_fallback": False, "metadata_fallback": False}
        monkeypatch.setattr(process_one, "process_compilation", fake_compilation)

        process_one.main()
        assert len(calls) == 1
        assert calls[0] == [a.resolve(), b.resolve()]
        out = capsys.readouterr().out
        assert "combining 2 clips" in out
        assert "combo.mp4" in out


class TestSingleFileMode:
    def test_missing_file_is_skipped_not_fatal(self, monkeypatch, tmp_path, cfg_factory, capsys):
        missing = tmp_path / "missing.mp4"
        monkeypatch.setattr("sys.argv", ["process_one", str(missing)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: [])
        process_one.main()  # must not raise
        out = capsys.readouterr().out
        assert "skip" in out
        assert "not found" in out

    def test_processes_each_existing_file(self, monkeypatch, tmp_path, cfg_factory):
        a = tmp_path / "a.mp4"
        a.write_bytes(b"x")
        b = tmp_path / "b.mp4"
        b.write_bytes(b"x")
        monkeypatch.setattr("sys.argv", ["process_one", str(a), str(b)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: [])

        processed = []
        monkeypatch.setattr(
            process_one, "process_video",
            lambda src, cfg, on_stage, on_progress: processed.append(src) or
            {"video": "out.mp4", "titles": [], "hashtags": [], "hook": "h",
             "metadata_fallback": False})
        process_one.main()
        assert processed == [a.resolve(), b.resolve()]

    def test_startup_warnings_are_printed(self, monkeypatch, tmp_path, cfg_factory, capsys):
        a = tmp_path / "a.mp4"
        a.write_bytes(b"x")
        monkeypatch.setattr("sys.argv", ["process_one", str(a)])
        monkeypatch.setattr(process_one, "load_settings", lambda: cfg_factory())
        monkeypatch.setattr(process_one, "startup_checks", lambda cfg: ["a warning"])
        monkeypatch.setattr(
            process_one, "process_video",
            lambda src, cfg, on_stage, on_progress:
            {"video": "out.mp4", "titles": [], "hashtags": [], "hook": "h",
             "metadata_fallback": False})
        process_one.main()
        out = capsys.readouterr().out
        assert "[warn] a warning" in out

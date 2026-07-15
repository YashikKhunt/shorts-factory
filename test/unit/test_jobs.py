"""Tests for backend/jobs.py: Job dataclass, snapshotting, and the worker
loop's job-lifecycle state transitions."""
import asyncio
import json

import pytest

from backend import jobs as jobs_mod


@pytest.fixture(autouse=True)
def _isolated_jobs_state(tmp_path, monkeypatch):
    """Every test gets a clean in-memory job registry and its own snapshot
    file, so tests never see each other's jobs or touch the real repo's
    jobs.json."""
    monkeypatch.setattr(jobs_mod, "jobs", {})
    monkeypatch.setattr(jobs_mod, "queue", asyncio.Queue())
    monkeypatch.setattr(jobs_mod, "SNAPSHOT", tmp_path / "jobs.json")
    yield


class TestJobDataclass:
    def test_public_hides_internal_path_fields(self):
        job = jobs_mod.Job(id="abc", filename="clip.mp4", src_path="/x/clip.mp4")
        pub = job.public()
        assert "src_path" not in pub
        assert "src_paths" not in pub
        assert pub["id"] == "abc"
        assert pub["status"] == "queued"

    def test_defaults(self):
        job = jobs_mod.Job(id="abc", filename="clip.mp4", src_path="/x/clip.mp4")
        assert job.status == "queued"
        assert job.stage == "queued"
        assert job.progress == 0.0
        assert job.error is None
        assert job.result is None
        assert job.src_paths == []


class TestCreateJob:
    def test_creates_job_with_uuid_and_registers_it(self, tmp_path):
        job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
        assert job.id in jobs_mod.jobs
        assert len(job.id) == 12  # uuid4().hex[:12]
        assert job.filename == "clip.mp4"

    def test_writes_snapshot_on_creation(self, tmp_path):
        jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
        assert jobs_mod.SNAPSHOT.exists()
        data = json.loads(jobs_mod.SNAPSHOT.read_text())
        assert len(data) == 1


class TestCreateCompilationJob:
    def test_filename_summarizes_clip_count(self):
        job = jobs_mod.create_compilation_job(["a.mp4", "b.mp4", "c.mp4"])
        assert job.filename == "3 clips – a.mp4"
        assert job.src_paths == []  # populated by the caller (main.py) later

    def test_registered_in_jobs_dict(self):
        job = jobs_mod.create_compilation_job(["a.mp4", "b.mp4"])
        assert jobs_mod.jobs[job.id] is job


class TestSnapshotRoundTrip:
    def test_save_and_load_restores_job(self, tmp_path):
        job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
        job.status = "done"
        job.result = {"video": "out.mp4"}
        jobs_mod.save_snapshot()

        jobs_mod.jobs.clear()
        jobs_mod.load_snapshot()
        assert job.id in jobs_mod.jobs
        restored = jobs_mod.jobs[job.id]
        assert restored.status == "done"
        assert restored.result == {"video": "out.mp4"}

    def test_running_job_marked_interrupted_on_load(self, tmp_path):
        job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
        job.status = "running"
        jobs_mod.save_snapshot()

        jobs_mod.jobs.clear()
        jobs_mod.load_snapshot()
        restored = jobs_mod.jobs[job.id]
        assert restored.status == "error"
        assert restored.error == "Interrupted by server restart"

    def test_load_snapshot_no_file_is_a_no_op(self):
        assert not jobs_mod.SNAPSHOT.exists()
        jobs_mod.load_snapshot()  # must not raise
        assert jobs_mod.jobs == {}

    def test_load_snapshot_malformed_json_is_ignored(self):
        jobs_mod.SNAPSHOT.write_text("{not valid json")
        jobs_mod.load_snapshot()  # must not raise
        assert jobs_mod.jobs == {}

    def test_load_snapshot_json_with_wrong_shape_is_ignored(self):
        jobs_mod.SNAPSHOT.write_text(json.dumps({"not": "a list"}))
        jobs_mod.load_snapshot()  # iterating a dict yields keys -> Job(**"id") -> TypeError, caught
        assert jobs_mod.jobs == {}

    def test_save_snapshot_handles_unwritable_path_gracefully(self, monkeypatch, tmp_path):
        bad_dir = tmp_path / "does_not_exist_and_readonly"
        monkeypatch.setattr(jobs_mod, "SNAPSHOT", bad_dir / "nested" / "jobs.json")
        # parent dir was never created -> write_text raises OSError, must be swallowed
        jobs_mod.save_snapshot()  # must not raise


class TestWorker:
    async def _wait_until(self, predicate, timeout=2.0, interval=0.01):
        elapsed = 0.0
        while not predicate() and elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval
        assert predicate(), "condition was never satisfied within timeout"

    def test_single_video_job_runs_to_completion(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            monkeypatch.setattr(jobs_mod, "process_video",
                                lambda src, cfg, on_stage, on_progress: {"video": "out.mp4"})
            job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await self._wait_until(lambda: job.status in ("done", "error"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert job.status == "done"
            assert job.result == {"video": "out.mp4"}
            assert job.progress == 100.0

        asyncio.run(scenario())

    def test_compilation_job_routes_to_process_compilation(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            calls = []

            def fake_compilation(srcs, cfg, on_stage, on_progress, name=None):
                calls.append((srcs, name))
                return {"video": "combo.mp4"}
            monkeypatch.setattr(jobs_mod, "process_compilation", fake_compilation)

            job = jobs_mod.create_compilation_job(["a.mp4", "b.mp4"])
            job.src_paths = [str(tmp_path / "a.mp4"), str(tmp_path / "b.mp4")]
            job.src_path = job.src_paths[0]

            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await self._wait_until(lambda: job.status in ("done", "error"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert job.status == "done"
            assert len(calls) == 1
            assert calls[0][1] == f"compilation_{job.id}"

        asyncio.run(scenario())

    def test_pipeline_exception_marks_job_errored(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            def boom(src, cfg, on_stage, on_progress):
                raise RuntimeError("ffmpeg blew up")
            monkeypatch.setattr(jobs_mod, "process_video", boom)

            job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await self._wait_until(lambda: job.status in ("done", "error"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert job.status == "error"
            assert job.stage == "error"
            assert "ffmpeg blew up" in job.error

        asyncio.run(scenario())

    def test_long_error_message_truncated_to_500_chars(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            def boom(src, cfg, on_stage, on_progress):
                raise RuntimeError("x" * 1000)
            monkeypatch.setattr(jobs_mod, "process_video", boom)

            job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await self._wait_until(lambda: job.status in ("done", "error"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert len(job.error) == 500

        asyncio.run(scenario())

    def test_unknown_job_id_in_queue_is_skipped_without_crashing(self, cfg, monkeypatch):
        async def scenario():
            calls = []
            monkeypatch.setattr(jobs_mod, "process_video",
                                lambda *a, **k: calls.append(1) or {"video": "x"})
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put("does-not-exist")
            await asyncio.sleep(0.05)  # give the worker a chance to (not) crash
            assert not task.done()  # worker must still be alive
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == []

        asyncio.run(scenario())

    def test_job_not_in_queued_status_is_skipped(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            calls = []
            monkeypatch.setattr(jobs_mod, "process_video",
                                lambda *a, **k: calls.append(1) or {"video": "x"})
            job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
            job.status = "error"  # e.g. already failed/cancelled before worker got to it
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == []
            assert job.status == "error"  # unchanged

        asyncio.run(scenario())

    def test_stage_callback_resets_progress_except_when_rendering(self, cfg, tmp_path, monkeypatch):
        async def scenario():
            seen_progress_during_render = []

            def fake_process_video(src, cfg, on_stage, on_progress):
                on_stage("probing")
                on_progress(42.0)  # should be wiped back to 0 on next non-render stage
                on_stage("selecting")
                seen_progress_during_render.append(("after_selecting", None))
                on_stage("rendering")
                on_progress(55.0)
                return {"video": "out.mp4"}
            monkeypatch.setattr(jobs_mod, "process_video", fake_process_video)

            job = jobs_mod.create_job("clip.mp4", tmp_path / "clip.mp4")
            task = asyncio.create_task(jobs_mod.worker(cfg))
            await jobs_mod.queue.put(job.id)
            await self._wait_until(lambda: job.status in ("done", "error"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert job.status == "done"

        asyncio.run(scenario())

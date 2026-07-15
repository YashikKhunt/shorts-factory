"""API-level tests for backend/main.py using FastAPI's TestClient.

Every test rewires `backend.main.cfg` to point at a pytest tmp_path (never
the real repo's uploads/output dirs), stubs out `startup_checks` (so the
suite doesn't depend on the host machine's ffmpeg build), and monkeypatches
the actual pipeline entry points (`process_video` / `process_compilation`)
so no real ffmpeg/whisper/Claude work ever happens.
"""
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import jobs as jobs_mod
from backend import main as main_mod
from backend.config import Paths, Settings


def _tiny_mp4_bytes() -> bytes:
    # Content doesn't need to be a real video: main.py only inspects the
    # filename extension before writing bytes to disk.
    return b"\x00\x00\x00\x18ftypmp42fake-not-a-real-video"


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Rewire the module-level `cfg`, job registry, and queue so this test
    file never touches real project directories or runs a real job."""
    test_cfg = Settings(paths=Paths(music_dir=tmp_path / "music",
                                    output_dir=tmp_path / "output",
                                    uploads_dir=tmp_path / "uploads"))
    for d in (test_cfg.paths.music_dir, test_cfg.paths.output_dir,
             test_cfg.paths.uploads_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(main_mod, "cfg", test_cfg)
    monkeypatch.setattr(main_mod, "startup_checks", lambda cfg: [])
    monkeypatch.setattr(jobs_mod, "jobs", {})
    import asyncio
    monkeypatch.setattr(jobs_mod, "queue", asyncio.Queue())
    monkeypatch.setattr(jobs_mod, "SNAPSHOT", tmp_path / "jobs.json")
    monkeypatch.setattr(jobs_mod, "load_snapshot", lambda: None)
    return test_cfg


@pytest.fixture
def client(app_env):
    with TestClient(main_mod.app) as c:
        yield c


class TestUploadValidation:
    def test_rejects_upload_with_no_video_files(self, client):
        resp = client.post("/api/upload",
                           files=[("files", ("notes.txt", io.BytesIO(b"hi"), "text/plain"))])
        assert resp.status_code == 400
        assert "No video files" in resp.json()["detail"]

    def test_accepts_single_valid_video(self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        resp = client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))])
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["jobs"]) == 1
        assert body["jobs"][0]["filename"] == "clip.mp4"
        assert body["jobs"][0]["status"] in ("queued", "running", "done")

    def test_non_video_files_filtered_out_of_a_mixed_upload(self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        resp = client.post("/api/upload", files=[
            ("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4")),
            ("files", ("readme.txt", io.BytesIO(b"hi"), "text/plain")),
        ])
        assert resp.status_code == 200
        assert len(resp.json()["jobs"]) == 1

    def test_combine_with_fewer_than_two_clips_falls_back_to_single_jobs(
            self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        resp = client.post(
            "/api/upload",
            data={"combine": "1"},
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))])
        assert resp.status_code == 200
        # only 1 clip -> combine path requires >= 2, falls back to per-file jobs
        assert len(resp.json()["jobs"]) == 1

    def test_combine_over_max_clips_returns_400(self, client, app_env, monkeypatch):
        app_env.compilation.max_clips = 2
        monkeypatch.setattr(jobs_mod, "process_compilation",
                            lambda *a, **k: {"video": "combo.mp4"})
        files = [("files", (f"clip{i}.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))
                for i in range(3)]
        resp = client.post("/api/upload", data={"combine": "1"}, files=files)
        assert resp.status_code == 400
        assert "up to 2 clips" in resp.json()["detail"]

    def test_combine_with_two_or_more_clips_creates_single_compilation_job(
            self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_compilation",
                            lambda *a, **k: {"video": "combo.mp4"})
        files = [("files", ("a.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4")),
                ("files", ("b.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))]
        resp = client.post("/api/upload", data={"combine": "1"}, files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["jobs"]) == 1
        assert "2 clips" in body["jobs"][0]["filename"]

    def test_upload_writes_files_under_configured_uploads_dir_not_real_repo(
            self, client, app_env, monkeypatch, tmp_path):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))])
        written = list(app_env.paths.uploads_dir.rglob("*.mp4"))
        assert len(written) == 1
        assert str(tmp_path) in str(written[0])

    def test_upload_sanitizes_unsafe_filename_characters(
            self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        client.post(
            "/api/upload",
            files=[("files", ("../../evil name!!.mp4", io.BytesIO(_tiny_mp4_bytes()),
                              "video/mp4"))])
        written = list(app_env.paths.uploads_dir.rglob("*.mp4"))
        assert len(written) == 1
        assert ".." not in written[0].name
        assert "!" not in written[0].name


class TestJobListingAndRetrieval:
    def test_list_jobs_empty_initially(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        assert resp.json() == {"jobs": [], "warnings": []}

    def test_list_jobs_ordered_newest_first(self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        client.post("/api/upload",
                   files=[("files", ("first.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))])
        client.post("/api/upload",
                   files=[("files", ("second.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))])
        jobs_list = client.get("/api/jobs").json()["jobs"]
        assert jobs_list[0]["filename"] == "second.mp4"
        assert jobs_list[1]["filename"] == "first.mp4"

    def test_get_unknown_job_returns_404(self, client):
        resp = client.get("/api/jobs/does-not-exist")
        assert resp.status_code == 404

    def test_get_known_job_returns_public_shape(self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        job_id = client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))],
        ).json()["jobs"][0]["id"]
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert "src_path" not in resp.json()


class TestDeleteJob:
    def test_delete_known_job_returns_ok(self, client, app_env, monkeypatch):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": "out.mp4"})
        job_id = client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))],
        ).json()["jobs"][0]["id"]
        resp = client.delete(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert client.get(f"/api/jobs/{job_id}").status_code == 404

    def test_delete_unknown_job_returns_404(self, client):
        resp = client.delete("/api/jobs/does-not-exist")
        assert resp.status_code == 404


class TestResultFileEndpoints:
    def _completed_job(self, client, app_env, monkeypatch, tmp_path):
        video = tmp_path / "result.mp4"
        video.write_bytes(b"fake-video-bytes")
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"fake-jpeg-bytes")
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": str(video), "thumbnail": str(thumb)})
        job_id = client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))],
        ).json()["jobs"][0]["id"]
        # poll until the (fast, mocked) worker marks the job done
        import time
        for _ in range(200):
            if jobs_mod.jobs[job_id].status == "done":
                break
            time.sleep(0.01)
        assert jobs_mod.jobs[job_id].status == "done"
        return job_id

    def test_video_endpoint_returns_404_when_job_missing_result(self, client):
        resp = client.get("/api/jobs/nope/video")
        assert resp.status_code == 404

    def test_video_endpoint_returns_404_when_job_not_yet_done(self, client, app_env, monkeypatch):
        async def never_finishes(*a, **k):
            import asyncio
            await asyncio.sleep(999)
        # create a job but never queue it -> result stays None
        job = jobs_mod.create_job("clip.mp4", Path("/tmp/whatever.mp4"))
        resp = client.get(f"/api/jobs/{job.id}/video")
        assert resp.status_code == 404

    def test_video_endpoint_returns_404_when_file_missing_on_disk(
            self, client, app_env, monkeypatch, tmp_path):
        monkeypatch.setattr(jobs_mod, "process_video",
                            lambda *a, **k: {"video": str(tmp_path / "gone.mp4")})
        job_id = client.post(
            "/api/upload",
            files=[("files", ("clip.mp4", io.BytesIO(_tiny_mp4_bytes()), "video/mp4"))],
        ).json()["jobs"][0]["id"]
        import time
        for _ in range(200):
            if jobs_mod.jobs[job_id].status == "done":
                break
            time.sleep(0.01)
        resp = client.get(f"/api/jobs/{job_id}/video")
        assert resp.status_code == 404
        assert "missing on disk" in resp.json()["detail"]

    def test_video_endpoint_serves_existing_file(self, client, app_env, monkeypatch, tmp_path):
        job_id = self._completed_job(client, app_env, monkeypatch, tmp_path)
        resp = client.get(f"/api/jobs/{job_id}/video")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "video/mp4"

    def test_thumbnail_endpoint_serves_existing_file(self, client, app_env, monkeypatch, tmp_path):
        job_id = self._completed_job(client, app_env, monkeypatch, tmp_path)
        resp = client.get(f"/api/jobs/{job_id}/thumbnail")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/jpeg"

    def test_download_endpoint_sets_filename(self, client, app_env, monkeypatch, tmp_path):
        job_id = self._completed_job(client, app_env, monkeypatch, tmp_path)
        resp = client.get(f"/api/jobs/{job_id}/download")
        assert resp.status_code == 200
        assert "result.mp4" in resp.headers["content-disposition"]

    def test_reveal_endpoint_ok_even_without_open_binary(
            self, client, app_env, monkeypatch, tmp_path):
        job_id = self._completed_job(client, app_env, monkeypatch, tmp_path)
        monkeypatch.setattr(main_mod.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))
        resp = client.post(f"/api/jobs/{job_id}/reveal")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestConfigEndpoints:
    def test_get_config_reflects_current_settings(self, client, app_env):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["music_mode"] == "duck"
        assert body["api_key_set"] is False

    def test_put_config_updates_target_duration(self, client, app_env):
        resp = client.put("/api/config", json={"target_duration": 42})
        assert resp.status_code == 200
        assert resp.json()["target_duration"] == 42
        assert app_env.video.target_duration == 42

    def test_put_config_ignores_unknown_keys(self, client, app_env):
        resp = client.put("/api/config", json={"not_a_real_field": 123})
        assert resp.status_code == 200
        assert "not_a_real_field" not in resp.json()

    def test_put_config_updates_music_mode(self, client, app_env):
        resp = client.put("/api/config", json={"music_mode": "mix"})
        assert resp.json()["music_mode"] == "mix"
        assert app_env.audio.music_mode == "mix"

"""FastAPI app: upload/queue/results API + serves the built frontend."""
import asyncio
import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import jobs
from .config import PROJECT_ROOT, load_settings, startup_checks

cfg = load_settings()
startup_warnings: list[str] = []

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    startup_warnings.extend(startup_checks(cfg))
    for w in startup_warnings:
        print(f"[warn] {w}")
    jobs.load_snapshot()
    task = asyncio.create_task(jobs.worker(cfg))
    yield
    task.cancel()


app = FastAPI(title="Shorts Factory", lifespan=lifespan)


async def _save_upload(f: UploadFile, dest: Path) -> None:
    with dest.open("wb") as out:
        while chunk := await f.read(1 << 20):
            out.write(chunk)


@app.post("/api/upload")
async def upload(files: list[UploadFile], combine: str = Form("0")):
    valid = [(f, Path(f.filename or "clip.mp4").name) for f in files
             if Path(f.filename or "clip.mp4").suffix.lower() in VIDEO_EXT]
    if not valid:
        raise HTTPException(400, "No video files in upload")

    if combine in ("1", "true", "on") and len(valid) >= 2:
        if len(valid) > cfg.compilation.max_clips:
            raise HTTPException(
                400, f"Combine supports up to {cfg.compilation.max_clips} clips")
        job = jobs.create_compilation_job([name for _, name in valid])
        job_dir = cfg.paths.uploads_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        for i, (f, name) in enumerate(valid):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
            dest = job_dir / f"{i:02d}_{safe}"  # index keeps selection order
            await _save_upload(f, dest)
            job.src_paths.append(str(dest))
        job.src_path = job.src_paths[0]
        jobs.save_snapshot()
        await jobs.queue.put(job.id)
        return {"jobs": [job.public()]}

    created = []
    for f, name in valid:
        job = jobs.create_job(name, Path())
        job_dir = cfg.paths.uploads_dir / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        dest = job_dir / safe
        await _save_upload(f, dest)
        job.src_path = str(dest)
        created.append(job.public())
        await jobs.queue.put(job.id)
    jobs.save_snapshot()
    return {"jobs": created}


@app.get("/api/jobs")
def list_jobs():
    ordered = sorted(jobs.jobs.values(), key=lambda j: j.created_at, reverse=True)
    return {"jobs": [j.public() for j in ordered], "warnings": startup_warnings}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.public()


def _result_file(job_id: str, key: str) -> Path:
    job = jobs.jobs.get(job_id)
    if job is None or job.result is None:
        raise HTTPException(404, "Result not available")
    path = Path(job.result[key])
    if not path.exists():
        raise HTTPException(404, "File missing on disk")
    return path


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str):
    return FileResponse(_result_file(job_id, "video"), media_type="video/mp4")


@app.get("/api/jobs/{job_id}/thumbnail")
def job_thumbnail(job_id: str):
    return FileResponse(_result_file(job_id, "thumbnail"), media_type="image/jpeg")


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    path = _result_file(job_id, "video")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@app.post("/api/jobs/{job_id}/reveal")
def job_reveal(job_id: str):
    path = _result_file(job_id, "video")
    try:
        subprocess.run(["open", "-R", str(path)], check=False)
    except FileNotFoundError:  # no `open` binary outside macOS (e.g. in Docker)
        pass
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.jobs.pop(job_id, None)
    if job is None:
        raise HTTPException(404, "Job not found")
    jobs.save_snapshot()
    return {"ok": True}


@app.get("/api/config")
def get_config():
    return {
        "music_mode": cfg.audio.music_mode,
        "target_duration": cfg.video.target_duration,
        "segment_strategy": cfg.video.segment_strategy,
        "aspect_strategy": cfg.video.aspect_strategy,
        "captions_enabled": cfg.captions.enabled,
        "hook_enabled": cfg.hook.enabled,
        "claude_model": cfg.claude.model,
        "api_key_set": cfg.anthropic_api_key is not None,
    }


@app.put("/api/config")
async def put_config(body: dict):
    editable = {"music_mode": ("audio", "music_mode"),
                "target_duration": ("video", "target_duration"),
                "segment_strategy": ("video", "segment_strategy"),
                "aspect_strategy": ("video", "aspect_strategy"),
                "captions_enabled": ("captions", "enabled"),
                "hook_enabled": ("hook", "enabled"),
                "claude_model": ("claude", "model")}
    for key, (section, attr) in editable.items():
        if key in body:
            setattr(getattr(cfg, section), attr, body[key])
    return JSONResponse(get_config())


dist = PROJECT_ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

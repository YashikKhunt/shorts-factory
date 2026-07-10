"""Job model, in-memory registry, and the single-worker processing queue.

One video renders at a time. Stage/progress fields are mutated from the worker
thread and read by the polling endpoints; a jobs.json snapshot survives
restarts (outputs are on disk regardless).
"""
import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .config import PROJECT_ROOT, Settings
from .pipeline.runner import process_video

SNAPSHOT = Path(os.environ.get("JOBS_SNAPSHOT") or PROJECT_ROOT / "jobs.json")
SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)

jobs: dict[str, "Job"] = {}
queue: asyncio.Queue = asyncio.Queue()


@dataclass
class Job:
    id: str
    filename: str
    src_path: str
    status: str = "queued"       # queued | running | done | error
    stage: str = "queued"
    progress: float = 0.0
    error: str | None = None
    result: dict | None = None
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("src_path")
        return d


def create_job(filename: str, src_path: Path) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], filename=filename, src_path=str(src_path))
    jobs[job.id] = job
    save_snapshot()
    return job


def save_snapshot() -> None:
    try:
        SNAPSHOT.write_text(json.dumps(
            [j.public() | {"src_path": j.src_path} for j in jobs.values()]))
    except OSError:
        pass


def load_snapshot() -> None:
    if not SNAPSHOT.exists():
        return
    try:
        for d in json.loads(SNAPSHOT.read_text()):
            job = Job(**d)
            if job.status == "running":  # interrupted by restart
                job.status, job.error = "error", "Interrupted by server restart"
            jobs[job.id] = job
    except (json.JSONDecodeError, TypeError):
        pass


async def worker(cfg: Settings) -> None:
    loop = asyncio.get_running_loop()
    while True:
        job_id: str = await queue.get()
        job = jobs.get(job_id)
        if job is None or job.status != "queued":
            continue
        job.status = "running"

        def on_stage(s: str, j: Job = job) -> None:
            j.stage = s
            if s != "rendering":
                j.progress = 0.0

        def on_progress(p: float, j: Job = job) -> None:
            j.progress = round(p, 1)

        try:
            result = await loop.run_in_executor(
                None, lambda: process_video(Path(job.src_path), cfg,
                                            on_stage, on_progress))
            job.result = result
            job.status, job.stage, job.progress = "done", "done", 100.0
        except Exception as e:  # keep the worker alive for the next job
            job.status, job.stage = "error", "error"
            job.error = str(e)[:500]
        save_snapshot()

# API-only backend: FastAPI + ffmpeg pipeline. The frontend is served by its
# own nginx container (see frontend.Dockerfile) which proxies /api here.
FROM python:3.11-slim-bookworm

# ffmpeg: required by startup_checks (needs overlay/loudnorm/sidechaincompress/amix,
# all present in Debian's build). fonts-dejavu-core: caption rendering via Pillow.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
# Linux-specific config: libx264 encoder (h264_videotoolbox is macOS-only).
COPY docker/config.docker.yaml ./config.yaml

# jobs.json lives in /app/data so it can sit on a persistent volume.
ENV JOBS_SNAPSHOT=/app/data/jobs.json \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# Single worker only: the job registry and queue are in-process (backend/jobs.py).
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

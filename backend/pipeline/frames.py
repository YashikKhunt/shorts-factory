"""Extract small representative JPEG frames for Claude vision + UI thumbnail."""
import subprocess
from pathlib import Path

FRACTIONS = (0.15, 0.5, 0.85)


def extract_frames(path: Path, start: float, duration: float, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, frac in enumerate(FRACTIONS):
        t = start + duration * frac
        out = out_dir / f"frame_{i}.jpg"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path),
             "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "3", str(out)],
            capture_output=True, text=True)
        if proc.returncode == 0 and out.exists():
            frames.append(out)
    if not frames:
        raise RuntimeError("Could not extract any frames from the video")
    return frames

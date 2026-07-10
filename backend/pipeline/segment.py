"""Pick the best target_duration window from the clip.

Strategy "energy": decode audio once to 16 kHz mono PCM, compute RMS per
0.5 s window, slide a target-length window and keep the highest mean energy —
in trip footage the loud moments (waves, crowds, engines, laughter) are
usually the interesting ones. Falls back to the start of the clip.

`energy_curve` / `candidate_windows` are also used by the compilation
pipeline: the raw RMS curve becomes AI evidence and the top-k windows are
both prompt hints and the deterministic fallback edit.
"""
import subprocess
from pathlib import Path

import numpy as np

from .probe import ProbeResult

WINDOW_S = 0.5
SAMPLE_RATE = 16000


def energy_curve(path: Path, info: ProbeResult) -> np.ndarray | None:
    """RMS per 0.5 s window over the whole file, or None (no audio / decode failure)."""
    if not info.has_audio:
        return None
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < SAMPLE_RATE:
        return None
    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(WINDOW_S * SAMPLE_RATE)
    n = len(pcm) // hop
    if n < 1:
        return None
    return np.sqrt(np.mean(pcm[: n * hop].reshape(n, hop) ** 2, axis=1))


def candidate_windows(rms: np.ndarray, window_s: float,
                      k: int = 3) -> list[tuple[float, float]]:
    """Top-k non-overlapping windows of `window_s` seconds: [(start, score)], best first."""
    n = len(rms)
    win = int(round(window_s / WINDOW_S))
    if win >= n:
        return [(0.0, float(np.mean(rms)))] if n else []
    cs = np.concatenate([[0.0], np.cumsum(rms)])
    means = (cs[win:] - cs[:-win]) / win
    out: list[tuple[float, float]] = []
    scores = means.copy()
    for _ in range(k):
        i = int(np.argmax(scores))
        if not np.isfinite(scores[i]) or scores[i] < 0:
            break
        out.append((i * WINDOW_S, float(means[i])))
        lo, hi = max(0, i - win + 1), min(len(scores), i + win)
        scores[lo:hi] = -1.0
        if (scores < 0).all():
            break
    return out


def select_segment(path: Path, info: ProbeResult, target: float,
                   strategy: str = "energy") -> tuple[float, float]:
    """Return (start, duration) in seconds."""
    if info.duration <= target + 0.5:
        return 0.0, info.duration
    if strategy != "energy" or not info.has_audio:
        return 0.0, target

    rms = energy_curve(path, info)
    if rms is None:
        return 0.0, target
    wins = candidate_windows(rms, target, k=1)
    if not wins or int(round(target / WINDOW_S)) >= len(rms):
        return 0.0, target
    start = min(wins[0][0], max(0.0, info.duration - target))
    return start, target

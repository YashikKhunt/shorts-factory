"""Pick the best target_duration window from the clip.

Strategy "energy": decode audio once to 16 kHz mono PCM, compute RMS per
0.5 s window, slide a target-length window and keep the highest mean energy —
in trip footage the loud moments (waves, crowds, engines, laughter) are
usually the interesting ones. Falls back to the start of the clip.
"""
import subprocess
from pathlib import Path

import numpy as np

from .probe import ProbeResult

WINDOW_S = 0.5
SAMPLE_RATE = 16000


def select_segment(path: Path, info: ProbeResult, target: float,
                   strategy: str = "energy") -> tuple[float, float]:
    """Return (start, duration) in seconds."""
    if info.duration <= target + 0.5:
        return 0.0, info.duration
    if strategy != "energy" or not info.has_audio:
        return 0.0, target

    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True)
    if proc.returncode != 0 or len(proc.stdout) < SAMPLE_RATE:
        return 0.0, target

    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(WINDOW_S * SAMPLE_RATE)
    n = len(pcm) // hop
    rms = np.sqrt(np.mean(pcm[: n * hop].reshape(n, hop) ** 2, axis=1))

    win = int(round(target / WINDOW_S))
    if win >= n:
        return 0.0, target
    # mean energy of each sliding window via cumulative sum
    cs = np.concatenate([[0.0], np.cumsum(rms)])
    means = (cs[win:] - cs[:-win]) / win
    start = float(np.argmax(means)) * WINDOW_S
    start = min(start, max(0.0, info.duration - target))
    return start, target

"""Build and run the single-pass ffmpeg render.

Inputs: [0] source video (seeked/trimmed), [1..n] overlay PNGs (still images;
`overlay` repeats the last frame, so timed `enable` windows just work),
[last] music track (stream-looped).
"""
import random
import subprocess
from pathlib import Path
from typing import Callable

from .captions import Overlay
from .probe import ProbeResult

MUSIC_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".flac")


def pick_music(music_dir: Path) -> Path | None:
    tracks = [p for p in sorted(music_dir.iterdir()) if p.suffix.lower() in MUSIC_EXTS]
    return random.choice(tracks) if tracks else None


def _aspect_filters(info: ProbeResult, strategy: str) -> str:
    if abs(info.aspect - 9 / 16) < 0.02:
        return "scale=1080:1920"
    if strategy == "pad":
        return ("scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
    return ("scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920")


def build_command(src: Path, out: Path, info: ProbeResult, start: float,
                  duration: float, overlays: list[Overlay],
                  music: Path | None, cfg) -> list[str]:
    v = cfg.video
    a = cfg.audio
    music_mode = a.music_mode if music else "none"

    cmd = ["ffmpeg", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    for ov in overlays:
        cmd += ["-i", str(ov.path)]
    music_idx = None
    if music_mode != "none":
        music_idx = 1 + len(overlays)
        cmd += ["-stream_loop", "-1", "-i", str(music)]

    # ---- video chain ----
    chain = [f"fps={v.fps}", _aspect_filters(info, v.aspect_strategy)]
    if v.color_grade.enabled:
        sat = v.color_grade.saturation * (1.1 if info.is_hdr else 1.0)
        chain.append(f"eq=saturation={sat:.2f}:contrast={v.color_grade.contrast}")
    chain.append("format=yuv420p")
    graph = [f"[0:v]{','.join(chain)}[v0]"]
    cur = "v0"
    for i, ov in enumerate(overlays):
        nxt = f"v{i + 1}"
        graph.append(f"[{cur}][{i + 1}:v]overlay=x=(W-w)/2:y={ov.y}"
                     f":enable='between(t,{ov.start:.2f},{ov.end:.2f})'[{nxt}]")
        cur = nxt
    fade_out_st = max(0.0, duration - v.fade.out)
    graph.append(f"[{cur}]fade=t=in:st=0:d={v.fade.in_},"
                 f"fade=t=out:st={fade_out_st:.2f}:d={v.fade.out}[vout]")

    # ---- audio chain ----
    if info.has_audio:
        graph.append(f"[0:a]loudnorm=I={a.loudnorm_target}:TP=-1.5:LRA=11[orig]")
    if music_idx is not None:
        mfade_st = max(0.0, duration - 0.8)
        graph.append(f"[{music_idx}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
                     f"volume={a.music_gain_db}dB,afade=t=in:st=0:d=0.6,"
                     f"afade=t=out:st={mfade_st:.2f}:d=0.8[mus]")

    if info.has_audio and music_idx is not None and music_mode == "duck":
        graph.append("[orig]asplit=2[o1][o2]")
        graph.append("[mus][o2]sidechaincompress=threshold=0.05:ratio=8"
                     ":attack=20:release=400[md]")
        graph.append("[o1][md]amix=inputs=2:duration=first:normalize=0[aout]")
    elif info.has_audio and music_idx is not None and music_mode == "mix":
        graph.append("[orig][mus]amix=inputs=2:duration=first:normalize=0[aout]")
    elif music_idx is not None:  # replace, or source has no audio
        graph.append("[mus]anull[aout]")
    elif info.has_audio:         # music_mode == none
        graph.append("[orig]anull[aout]")
    else:                        # no audio anywhere: silent track
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        graph.append(f"[{1 + len(overlays)}:a]anull[aout]")

    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]"]

    if v.encoder == "libx264":
        cmd += ["-c:v", "libx264", "-crf", str(v.crf), "-preset", "medium"]
    else:
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", v.bitrate]
    cmd += ["-r", str(v.fps), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{duration:.3f}", str(out)]
    return cmd


def run_render(cmd: list[str], duration: float,
               on_progress: Callable[[float], None] | None = None) -> None:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("out_time_us=") and on_progress:
            try:
                pct = min(100.0, int(line.split("=")[1]) / (duration * 1e6) * 100)
                on_progress(pct)
            except ValueError:
                pass
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg render failed: {err.strip()[-400:]}")

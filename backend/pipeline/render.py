"""Build and run ffmpeg renders.

Single-clip Shorts use one pass (`build_command`): [0] source video
(seeked/trimmed), [1..n] overlay PNGs (still images; `overlay` repeats the
last frame, so timed `enable` windows just work), [last] music track
(stream-looped).

Compilations use two passes: `build_normalize_command` renders each chosen
clip range to a mezzanine with identical codec/fps/resolution/audio params
(per-clip reframing and loudness happen here), then `build_final_command`
concat-demuxes the mezzanines and applies overlays/music/fades — the same
graph as the single-clip pass, minus loudnorm.
"""
import random
import subprocess
from pathlib import Path
from typing import Callable

from .captions import Overlay
from .probe import ProbeResult

MUSIC_EXTS = (".mp3", ".m4a", ".wav", ".aac", ".flac")

MEZZ_SAMPLE_RATE = 48000


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


def _video_norm_chain(info: ProbeResult, cfg) -> list[str]:
    """fps + 9:16 reframe + color grade + pixel format, per-source."""
    v = cfg.video
    chain = [f"fps={v.fps}", _aspect_filters(info, v.aspect_strategy)]
    if v.color_grade.enabled:
        sat = v.color_grade.saturation * (1.1 if info.is_hdr else 1.0)
        chain.append(f"eq=saturation={sat:.2f}:contrast={v.color_grade.contrast}")
    chain.append("format=yuv420p")
    return chain


def _overlay_graph(cur: str, overlays: list[Overlay]) -> tuple[list[str], str]:
    """Chain overlay inputs [1..n] onto `cur`; returns (graph lines, last label)."""
    graph = []
    for i, ov in enumerate(overlays):
        nxt = f"v{i + 1}"
        graph.append(f"[{cur}][{i + 1}:v]overlay=x=(W-w)/2:y={ov.y}"
                     f":enable='between(t,{ov.start:.2f},{ov.end:.2f})'[{nxt}]")
        cur = nxt
    return graph, cur


def _fade_step(cur: str, duration: float, cfg) -> str:
    v = cfg.video
    fade_out_st = max(0.0, duration - v.fade.out)
    return (f"[{cur}]fade=t=in:st=0:d={v.fade.in_},"
            f"fade=t=out:st={fade_out_st:.2f}:d={v.fade.out}[vout]")


def _audio_graph(has_audio: bool, music_idx: int | None, music_mode: str,
                 duration: float, cfg, silent_idx: int,
                 loudnorm: bool = True) -> tuple[list[str], list[str]]:
    """Audio filtergraph lines + extra input args (anullsrc when fully silent).

    `silent_idx` is the input index the anullsrc source would get if added.
    `loudnorm=False` passes [0:a] through untouched (compilation final pass —
    loudness was normalized per clip).
    """
    a = cfg.audio
    graph: list[str] = []
    extra: list[str] = []
    if has_audio:
        if loudnorm:
            graph.append(f"[0:a]loudnorm=I={a.loudnorm_target}:TP=-1.5:LRA=11[orig]")
        else:
            graph.append("[0:a]anull[orig]")
    if music_idx is not None:
        mfade_st = max(0.0, duration - 0.8)
        graph.append(f"[{music_idx}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
                     f"volume={a.music_gain_db}dB,afade=t=in:st=0:d=0.6,"
                     f"afade=t=out:st={mfade_st:.2f}:d=0.8[mus]")

    if has_audio and music_idx is not None and music_mode == "duck":
        graph.append("[orig]asplit=2[o1][o2]")
        graph.append("[mus][o2]sidechaincompress=threshold=0.05:ratio=8"
                     ":attack=20:release=400[md]")
        graph.append("[o1][md]amix=inputs=2:duration=first:normalize=0[aout]")
    elif has_audio and music_idx is not None and music_mode == "mix":
        graph.append("[orig][mus]amix=inputs=2:duration=first:normalize=0[aout]")
    elif music_idx is not None:  # replace, or source has no audio
        graph.append("[mus]anull[aout]")
    elif has_audio:              # music_mode == none
        graph.append("[orig]anull[aout]")
    else:                        # no audio anywhere: silent track
        extra += ["-f", "lavfi", "-t", f"{duration:.3f}",
                  "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        graph.append(f"[{silent_idx}:a]anull[aout]")
    return graph, extra


def _encoder_args(cfg) -> list[str]:
    v = cfg.video
    if v.encoder == "libx264":
        return ["-c:v", "libx264", "-crf", str(v.crf), "-preset", "medium"]
    return ["-c:v", "h264_videotoolbox", "-b:v", v.bitrate]


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

    graph = [f"[0:v]{','.join(_video_norm_chain(info, cfg))}[v0]"]
    ov_graph, cur = _overlay_graph("v0", overlays)
    graph += ov_graph
    graph.append(_fade_step(cur, duration, cfg))

    a_graph, extra = _audio_graph(info.has_audio, music_idx, music_mode,
                                  duration, cfg, silent_idx=1 + len(overlays))
    cmd += extra
    graph += a_graph

    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]"]
    cmd += _encoder_args(cfg)
    cmd += ["-r", str(v.fps), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{duration:.3f}", str(out)]
    return cmd


def build_normalize_command(src: Path, out: Path, info: ProbeResult,
                            start: float, duration: float, cfg) -> list[str]:
    """Pass 1 of a compilation: one clip range → mezzanine with params shared
    by every intermediate (1080x1920, cfg fps, yuv420p, 48 kHz stereo AAC),
    so the concat demuxer can join them. Slightly higher quality than the
    final encode since it gets re-encoded once more."""
    v = cfg.video
    a = cfg.audio

    cmd = ["ffmpeg", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(src)]
    graph = [f"[0:v]{','.join(_video_norm_chain(info, cfg))}[v]"]
    if info.has_audio:
        graph.append(f"[0:a]loudnorm=I={a.loudnorm_target}:TP=-1.5:LRA=11,"
                     f"aresample={MEZZ_SAMPLE_RATE}[a]")
    else:
        cmd += ["-f", "lavfi", "-t", f"{duration:.3f}",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate={MEZZ_SAMPLE_RATE}"]
        graph.append("[1:a]anull[a]")

    cmd += ["-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]"]
    if v.encoder == "libx264":
        cmd += ["-c:v", "libx264", "-crf", str(max(v.crf - 4, 14)),
                "-preset", "veryfast"]
    else:
        cmd += ["-c:v", "h264_videotoolbox", "-b:v", v.bitrate]
    cmd += ["-r", str(v.fps), "-c:a", "aac", "-b:a", "256k",
            "-ar", str(MEZZ_SAMPLE_RATE), "-ac", "2",
            "-t", f"{duration:.3f}", str(out)]
    return cmd


def write_concat_list(parts: list[Path], out: Path) -> Path:
    lines = []
    for p in parts:
        escaped = str(p).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    out.write_text("\n".join(lines) + "\n")
    return out


def build_final_command(concat_list: Path, out: Path, total: float,
                        overlays: list[Overlay], music: Path | None,
                        cfg) -> list[str]:
    """Pass 2 of a compilation: concat-demux the mezzanines, then the same
    overlay/fade/music graph as the single-clip pass. No loudnorm (done per
    clip); the concat stream always has audio (pass 1 guarantees it)."""
    v = cfg.video
    a = cfg.audio
    music_mode = a.music_mode if music else "none"

    cmd = ["ffmpeg", "-y", "-v", "error", "-progress", "pipe:1", "-nostats",
           "-f", "concat", "-safe", "0", "-i", str(concat_list)]
    for ov in overlays:
        cmd += ["-i", str(ov.path)]
    music_idx = None
    if music_mode != "none":
        music_idx = 1 + len(overlays)
        cmd += ["-stream_loop", "-1", "-i", str(music)]

    graph = ["[0:v]format=yuv420p[v0]"]
    ov_graph, cur = _overlay_graph("v0", overlays)
    graph += ov_graph
    graph.append(_fade_step(cur, total, cfg))

    a_graph, extra = _audio_graph(True, music_idx, music_mode, total, cfg,
                                  silent_idx=1 + len(overlays), loudnorm=False)
    cmd += extra
    graph += a_graph

    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]"]
    cmd += _encoder_args(cfg)
    cmd += ["-r", str(v.fps), "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)]
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

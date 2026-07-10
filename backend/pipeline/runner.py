"""Per-job orchestration: runs every pipeline stage in order and reports
progress via callbacks. Used by both the web app worker and the CLI harness."""
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from . import captions, frames, metadata_ai, render, segment, transcribe
from .probe import probe

SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_stem(name: str) -> str:
    return SAFE_NAME.sub("_", Path(name).stem).strip("_") or "clip"


def process_video(src: Path, cfg,
                  on_stage: Callable[[str], None] = lambda s: None,
                  on_progress: Callable[[float], None] = lambda p: None) -> dict:
    """Run the full pipeline on one file. Returns a result dict."""
    stem = _safe_stem(src.name)
    out_dir = cfg.paths.output_dir / stem
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    on_stage("probing")
    info = probe(src)

    on_stage("selecting")
    start, duration = segment.select_segment(
        src, info, cfg.video.target_duration, cfg.video.segment_strategy)

    transcript_segments = None
    if cfg.captions.enabled and info.has_audio:
        on_stage("transcribing")
        wav = work_dir / "segment.wav"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}",
             "-t", f"{duration:.3f}", "-i", str(src),
             "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            check=True, capture_output=True)
        transcript_segments = transcribe.transcribe(wav, cfg)

    on_stage("analyzing")
    frame_paths = frames.extract_frames(src, start, duration, work_dir)
    meta = metadata_ai.generate_metadata(
        frame_paths, info, src.name, transcript_segments, cfg)

    overlays = []
    if cfg.hook.enabled and meta.hook:
        overlays.append(captions.build_hook_overlay(meta.hook, cfg, work_dir))
    if transcript_segments:
        overlays.extend(captions.build_caption_overlays(
            transcript_segments, cfg, work_dir))

    on_stage("rendering")
    music = render.pick_music(cfg.paths.music_dir) \
        if cfg.audio.music_mode != "none" else None
    out_mp4 = out_dir / f"{stem}_short.mp4"
    cmd = render.build_command(src, out_mp4, info, start, duration,
                               overlays, music, cfg)
    render.run_render(cmd, duration, on_progress)

    on_stage("writing_outputs")
    thumb = out_dir / "thumbnail.jpg"
    shutil.copy(frame_paths[len(frame_paths) // 2], thumb)
    result = {
        "video": str(out_mp4),
        "thumbnail": str(thumb),
        "titles": meta.titles,
        "hashtags": meta.hashtags,
        "hook": meta.hook,
        "location_guess": meta.location_guess,
        "transcript": meta.transcript,
        "metadata_fallback": meta.fallback,
        "music": music.name if music else None,
        "segment": {"start": round(start, 2), "duration": round(duration, 2)},
        "source": {"name": src.name, "duration": round(info.duration, 2),
                   "resolution": f"{info.width}x{info.height}",
                   "gps": info.gps, "creation_time": info.creation_time},
    }
    (out_dir / f"{stem}_metadata.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False))
    (out_dir / f"{stem}_metadata.txt").write_text(_human_metadata(result))
    shutil.rmtree(work_dir, ignore_errors=True)
    return result


def _human_metadata(r: dict) -> str:
    lines = ["=== TITLES (pick one) ==="]
    lines += [f"{i + 1}. {t}" for i, t in enumerate(r["titles"])]
    lines += ["", "=== HASHTAGS (paste into description) ===",
              " ".join(r["hashtags"]),
              "", f"Hook overlay: {r['hook']}"]
    if r.get("location_guess"):
        lines.append(f"Location: {r['location_guess']}")
    if r.get("transcript"):
        lines += ["", "=== TRANSCRIPT ===", r["transcript"]]
    if r.get("clips"):
        lines += ["", "=== EDIT ==="]
        lines += [f"{i + 1}. {c['name']}  "
                  f"{c['source_start']:.1f}s-{c['source_start'] + c['duration']:.1f}s"
                  f"  → timeline {c['timeline_start']:.1f}s"
                  for i, c in enumerate(r["clips"])]
    if r.get("metadata_fallback"):
        lines += ["", "(!) Offline fallback metadata — set ANTHROPIC_API_KEY for AI titles."]
    lines.append("")
    return "\n".join(lines)

"""Compilation pipeline: cut several clips into ONE Short.

Per clip: probe → frames/energy/transcript evidence → AI (or fallback) edit
decision → normalize each chosen range to a mezzanine → concat → final render
with rebased captions, hook, music, and fades. Clips are ordered by recorded
creation_time when every clip has one, otherwise by selection order.
"""
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import captions, edit_ai, frames, metadata_ai, render, segment, transcribe
from .probe import probe
from .runner import _human_metadata


def _parse_ct(ct: str | None) -> datetime | None:
    if not ct:
        return None
    try:
        dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def process_compilation(srcs: list[Path], cfg,
                        on_stage: Callable[[str], None] = lambda s: None,
                        on_progress: Callable[[float], None] = lambda p: None,
                        name: str | None = None) -> dict:
    """Run the compilation pipeline over 2+ files. Returns a result dict with
    the same keys as runner.process_video plus `clips` and `edit_fallback`."""
    name = name or f"compilation_{int(time.time())}"
    out_dir = cfg.paths.output_dir / name
    work_dir = out_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    target = cfg.video.target_duration

    on_stage("probing")
    clips = [(src, probe(src)) for src in srcs]

    cts = [_parse_ct(info.creation_time) for _, info in clips]
    if all(ct is not None for ct in cts):
        clips = [clip for _, clip in sorted(zip(cts, clips), key=lambda p: p[0])]

    on_stage("analyzing_clips")
    evidence: list[edit_ai.ClipEvidence] = []
    for i, (src, info) in enumerate(clips):
        clip_dir = work_dir / f"clip_{i}"
        frame_paths = frames.extract_frames(src, 0.0, info.duration, clip_dir)
        rms = segment.energy_curve(src, info)
        cands = segment.candidate_windows(
            rms, min(target, info.duration), k=3) if rms is not None else []
        evidence.append(edit_ai.ClipEvidence(
            index=i, name=src.name, info=info, frames=frame_paths,
            frame_times=[info.duration * f for f in frames.FRACTIONS],
            energy=rms, candidates=cands, transcript=None))

    if cfg.captions.enabled:
        on_stage("transcribing")
        for i, (src, info) in enumerate(clips):
            if not info.has_audio:
                continue
            wav = work_dir / f"clip_{i}" / "full.wav"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(src),
                 "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                check=True, capture_output=True)
            evidence[i].transcript = transcribe.transcribe(wav, cfg)

    on_stage("deciding_edit")
    cuts, edit_fallback = edit_ai.decide_edit(evidence, target, cfg)
    total = round(sum(c.duration for c in cuts), 3)

    # rebase per-clip transcript segments onto the compilation timeline
    merged: list[tuple[float, float, str]] = []
    offsets: list[float] = []
    offset = 0.0
    for cut in cuts:
        offsets.append(offset)
        for s, e, text in evidence[cut.index].transcript or []:
            o_start = max(s, cut.start)
            o_end = min(e, cut.start + cut.duration)
            overlap = o_end - o_start
            if overlap <= 0:
                continue
            if overlap / max(e - s, 1e-6) < 0.3 and overlap < 0.5:
                continue  # sliver straddling a cut boundary — skip the flash
            merged.append((round(o_start - cut.start + offset, 2),
                           round(o_end - cut.start + offset, 2), text))
        offset += cut.duration

    on_stage("analyzing")
    used_frames = [f for c in cuts for f in evidence[c.index].frames][:9]
    names = ", ".join(evidence[c.index].name for c in cuts)
    moments = "; ".join(
        f"{evidence[c.index].name} at {c.start:.0f}-{c.start + c.duration:.0f}s"
        for c in cuts)
    meta = metadata_ai.generate_metadata(
        used_frames, evidence[cuts[0].index].info,
        f"{len(cuts)} clip trip compilation", merged or None, cfg,
        extra_context=[
            f"This Short is a compilation cut from {len(cuts)} clips: {names}.",
            f"Moments used: {moments}."])

    overlays = []
    if cfg.hook.enabled and meta.hook:
        overlays.append(captions.build_hook_overlay(meta.hook, cfg, work_dir))
    if merged:
        overlays.extend(captions.build_caption_overlays(merged, cfg, work_dir))

    on_stage("rendering")
    norm_parts: list[Path] = []
    done = 0.0
    for i, cut in enumerate(cuts):  # normalize passes fill progress 0→70
        src, info = clips[cut.index]
        part = work_dir / f"norm_{i}.mp4"
        cmd = render.build_normalize_command(src, part, info,
                                             cut.start, cut.duration, cfg)
        base, span = done / total * 70, cut.duration / total * 70
        render.run_render(cmd, cut.duration,
                          lambda p, b=base, s=span: on_progress(b + p * s / 100))
        norm_parts.append(part)
        done += cut.duration

    concat_list = render.write_concat_list(norm_parts, work_dir / "concat.txt")
    music = render.pick_music(cfg.paths.music_dir) \
        if cfg.audio.music_mode != "none" else None
    out_mp4 = out_dir / f"{name}_short.mp4"
    cmd = render.build_final_command(concat_list, out_mp4, total,
                                     overlays, music, cfg)
    render.run_render(cmd, total, lambda p: on_progress(70 + p * 0.30))

    on_stage("writing_outputs")
    thumb = out_dir / "thumbnail.jpg"  # frame of the actual edit, not a source
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{total / 2:.2f}",
         "-i", str(out_mp4), "-frames:v", "1", "-vf", "scale=768:-2",
         "-q:v", "3", str(thumb)],
        check=True, capture_output=True)

    used = [evidence[c.index] for c in cuts]
    gps = next((ev.info.gps for ev in used if ev.info.gps), None)
    earliest = min((ev.info.creation_time for ev in used
                    if ev.info.creation_time), default=None)
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
        "segment": {"start": 0.0, "duration": round(total, 2)},
        "source": {"name": f"{len(cuts)} clips", "duration": round(total, 2),
                   "resolution": "1080x1920", "gps": gps,
                   "creation_time": earliest},
        "clips": [{"name": ev.name,
                   "source_start": round(c.start, 2),
                   "duration": round(c.duration, 2),
                   "timeline_start": round(off, 2),
                   "creation_time": ev.info.creation_time}
                  for c, ev, off in zip(cuts, used, offsets)],
        "edit_fallback": edit_fallback,
    }
    (out_dir / f"{name}_metadata.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False))
    (out_dir / f"{name}_metadata.txt").write_text(_human_metadata(result))
    shutil.rmtree(work_dir, ignore_errors=True)
    return result

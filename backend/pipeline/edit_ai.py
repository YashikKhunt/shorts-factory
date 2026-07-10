"""Claude decides the compilation edit: which time range of each clip to use.

Evidence per clip — sampled frames, timestamped transcript, and an audio-energy
summary — goes to Claude, which returns an edit decision list (EDL). The output
is strictly validated and clamped; on any failure (no key, API error, garbage
EDL) a deterministic energy-based fallback produces the cuts instead, so the
render never blocks on this stage.
"""
import base64
import json
from dataclasses import dataclass
from pathlib import Path

import anthropic
import numpy as np

from . import segment
from .metadata_ai import cfg_key_present
from .probe import ProbeResult

EDL_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "use": {"type": "boolean"},
                    "start": {"type": "number"},
                    "duration": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "use", "start", "duration", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clips"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a short-form video editor cutting a single \
~{target:.0f}-second YouTube Short from {n} trip clips, joined with hard cuts \
in the given clip order. For each clip choose the single best contiguous time \
range — or skip a clip that adds nothing. Prefer moments with speech, visible \
action, or audio-energy peaks; use the transcript timestamps to avoid cutting \
mid-sentence; vary the pacing — the strongest clip may deserve more screen \
time. Every range must lie inside its clip's duration. The used durations must \
sum to {target:.0f}±2 seconds, and each used range must be at least \
{min_clip:.1f} seconds (or the whole clip if it is shorter than that). Give a \
one-line reason per clip."""


@dataclass
class ClipEvidence:
    index: int
    name: str
    info: ProbeResult
    frames: list[Path]
    frame_times: list[float]
    energy: np.ndarray | None                       # RMS per 0.5s, or None
    candidates: list[tuple[float, float]]           # (start, score), best first
    transcript: list[tuple[float, float, str]] | None  # clip-absolute times


@dataclass
class ClipCut:
    index: int
    start: float
    duration: float


def fallback_edit(evidence: list[ClipEvidence], target: float,
                  min_clip: float) -> list[ClipCut]:
    """Even time split; short clips take their whole length and the remainder
    redistributes. Windows placed on the energy peak, or centered if silent."""
    remaining = target
    durations: dict[int, float] = {}
    # allot shortest-first so clips that can't fill their share release time early
    for i, ev in sorted(enumerate(evidence), key=lambda p: p[1].info.duration):
        left = len(evidence) - len(durations)
        alloted = remaining / left
        d = min(alloted, ev.info.duration)
        d = max(d, min(min_clip, ev.info.duration))
        durations[i] = d
        remaining = max(0.0, remaining - d)

    cuts = []
    for i, ev in enumerate(evidence):  # emit in chronological (evidence) order
        d = durations[i]
        start = max(0.0, (ev.info.duration - d) / 2)  # centered default
        if ev.energy is not None:
            wins = segment.candidate_windows(ev.energy, d, k=1)
            if wins:
                start = min(wins[0][0], max(0.0, ev.info.duration - d))
        cuts.append(ClipCut(index=ev.index, start=round(start, 2),
                            duration=round(d, 2)))
    return cuts


def _validate(raw: dict, evidence: list[ClipEvidence], target: float,
              min_clip: float) -> list[ClipCut] | None:
    by_index = {ev.index: ev for ev in evidence}
    cuts: dict[int, ClipCut] = {}
    for item in raw.get("clips", []):
        idx = item.get("index")
        if idx not in by_index or idx in cuts or not item.get("use"):
            continue
        try:
            start, dur = float(item["start"]), float(item["duration"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (np.isfinite(start) and np.isfinite(dur)) or dur <= 0 or start < 0:
            return None
        clip_dur = by_index[idx].info.duration
        min_c = min(min_clip, clip_dur)
        start = min(max(0.0, start), max(0.0, clip_dur - min_c))
        dur = min(max(dur, min_c), clip_dur - start, target)
        cuts[idx] = ClipCut(index=idx, start=start, duration=dur)

    if len(cuts) < min(2, len(evidence)):
        return None

    total = sum(c.duration for c in cuts.values())
    if total <= 0:
        return None
    if abs(total - target) / target > 0.15:
        scale = target / total
        for c in cuts.values():
            clip_dur = by_index[c.index].info.duration
            min_c = min(min_clip, clip_dur)
            c.duration = min(max(c.duration * scale, min_c),
                             clip_dur - c.start)
        total = sum(c.duration for c in cuts.values())
    if total > target + 5:
        return None

    # chronological clip order regardless of how the AI ordered its answer
    ordered = [cuts[ev.index] for ev in evidence if ev.index in cuts]
    for c in ordered:
        c.start, c.duration = round(c.start, 2), round(c.duration, 2)
    return ordered


def _energy_summary(ev: ClipEvidence, target: float) -> str:
    rms = ev.energy
    assert rms is not None
    buckets = 20
    n = len(rms)
    idx = np.linspace(0, n, buckets + 1).astype(int)
    pooled = np.array([rms[a:b].mean() if b > a else 0.0
                       for a, b in zip(idx[:-1], idx[1:])])
    peak = pooled.max() or 1.0
    step = ev.info.duration / buckets
    curve = " ".join(f"t={i * step:.1f}:{v / peak:.2f}"
                     for i, v in enumerate(pooled))
    cands = ", ".join(f"start={s:.1f}s (score {sc / peak:.2f})"
                      for s, sc in ev.candidates)
    return (f"Audio energy (0-1, normalized) over the clip: {curve}\n"
            f"Highest-energy windows of ~{target:.0f}s: {cands}")


def _clip_blocks(ev: ClipEvidence, target: float) -> list[dict]:
    header = (f'CLIP {ev.index} "{ev.name}": {ev.info.duration:.1f}s, '
              f'recorded {ev.info.creation_time or "unknown"}, '
              f'audio: {"yes" if ev.info.has_audio else "no"}. '
              f'Frames below were taken at '
              f't={", ".join(f"{t:.1f}" for t in ev.frame_times)}s.')
    blocks: list[dict] = [{"type": "text", "text": header}]
    for f in ev.frames:
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(f.read_bytes()).decode()},
        })
    if ev.energy is not None:
        blocks.append({"type": "text", "text": _energy_summary(ev, target)})
    if ev.transcript:
        lines = "\n".join(f"[{s:.1f}s-{e:.1f}s] {t}" for s, e, t in ev.transcript)
        blocks.append({"type": "text", "text": f"Speech transcript:\n{lines}"})
    else:
        blocks.append({"type": "text", "text": "No speech detected."})
    return blocks


def decide_edit(evidence: list[ClipEvidence], target: float,
                cfg) -> tuple[list[ClipCut], bool]:
    """Return (cuts in chronological clip order, used_fallback)."""
    min_clip = cfg.compilation.min_clip_seconds
    if not cfg_key_present(cfg):
        return fallback_edit(evidence, target, min_clip), True

    content: list[dict] = []
    for ev in evidence:
        content += _clip_blocks(ev, target)
    content.append({"type": "text", "text":
                    f"Plan the edit: {len(evidence)} clips, total "
                    f"{target:.0f}±2s, minimum {min_clip:.1f}s per used clip."})

    system = SYSTEM_PROMPT.format(target=target, n=len(evidence),
                                  min_clip=min_clip)
    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=cfg.claude.model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": EDL_SCHEMA}},
        )
        data = response.parsed_output
        if data is None:
            data = json.loads(next(b.text for b in response.content
                                   if b.type == "text"))
        for item in data.get("clips", []):
            print(f"[edit] clip {item.get('index')}: use={item.get('use')} "
                  f"start={item.get('start')} dur={item.get('duration')} "
                  f"— {item.get('reason')}")
        cuts = _validate(data, evidence, target, min_clip)
        if cuts is not None:
            return cuts, False
        print("[edit] AI edit failed validation — using fallback")
    except anthropic.APIStatusError as e:
        print(f"[edit] Claude API error {e.status_code}: {e.message} — using fallback")
    except anthropic.APIConnectionError as e:
        print(f"[edit] connection error: {e} — using fallback")
    except (KeyError, StopIteration, json.JSONDecodeError, TypeError) as e:
        print(f"[edit] unexpected response shape: {e} — using fallback")
    return fallback_edit(evidence, target, min_clip), True

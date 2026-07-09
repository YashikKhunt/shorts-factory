"""Claude vision → titles, hashtags, and the on-video hook line.

Uses structured outputs (messages.parse + output_config.format) so the JSON is
schema-guaranteed. On any API failure the job continues with offline fallback
metadata — the video render must never block on this stage.
"""
import base64
import json
from dataclasses import dataclass, field
from pathlib import Path

import anthropic

from .probe import ProbeResult

SCHEMA = {
    "type": "object",
    "properties": {
        "titles": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "hook": {"type": "string"},
        "location_guess": {"type": ["string", "null"]},
    },
    "required": ["titles", "hashtags", "hook", "location_guess"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You write metadata for YouTube travel Shorts. From the video \
frames and context, produce:
1. titles: exactly {title_count} title options, each under 70 characters, using \
proven engagement patterns — curiosity gap ("You won't believe what's at the \
top…"), POV framing ("POV: sunrise from…"), specific place + superlative, or a \
question hook. No clickbait lies, at most one emoji per title.
2. hashtags: 8-12 tags, lowercase, no duplicates. Always start with #shorts and \
#travel, then 2-3 broad tags from this pool: {broad_pool}, then 4-6 niche or \
location tags inferred from the frames/GPS. Niche direction: {niche_hint}.
3. hook: at most 6 punchy words for a text overlay shown on-screen in the first \
2 seconds. It must complement, not duplicate, the titles.
4. location_guess: the most specific place you can identify from GPS/visuals, \
or null."""


@dataclass
class VideoMetadata:
    titles: list[str]
    hashtags: list[str]
    hook: str
    location_guess: str | None = None
    fallback: bool = False
    transcript: str | None = None
    extra: dict = field(default_factory=dict)


def _fallback_metadata(src_name: str, cfg, transcript: str | None) -> VideoMetadata:
    stem = Path(src_name).stem.replace("_", " ").replace("-", " ").strip().title()
    return VideoMetadata(
        titles=[f"{stem} — you have to see this",
                f"POV: {stem}",
                f"This is {stem} 🤯"],
        hashtags=list(dict.fromkeys(["#shorts", "#travel"] + cfg.hashtags.broad)),
        hook=cfg.hook.fallback_text,
        fallback=True,
        transcript=transcript)


def generate_metadata(frames: list[Path], info: ProbeResult, src_name: str,
                      transcript_segments: list[tuple[float, float, str]] | None,
                      cfg) -> VideoMetadata:
    transcript = " ".join(t for _, _, t in transcript_segments) \
        if transcript_segments else None
    if not cfg_key_present(cfg):
        return _fallback_metadata(src_name, cfg, transcript)

    context_lines = [f"Clip duration: {info.duration:.0f}s travel footage."]
    if info.creation_time:
        context_lines.append(f"Recorded: {info.creation_time}")
    if info.gps:
        context_lines.append(f"GPS coordinates: {info.gps[0]:.5f}, {info.gps[1]:.5f}")
    context_lines.append(f"Speech transcript: {transcript}" if transcript
                         else "No speech — ambient trip footage.")

    content = []
    for f in frames:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(f.read_bytes()).decode()},
        })
    content.append({"type": "text", "text": "\n".join(context_lines)})

    system = SYSTEM_PROMPT.format(
        title_count=cfg.claude.title_count,
        broad_pool=" ".join(cfg.hashtags.broad),
        niche_hint=cfg.hashtags.niche_hint)

    try:
        client = anthropic.Anthropic()
        response = client.messages.parse(
            model=cfg.claude.model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        )
        data = response.parsed_output
        if data is None:
            data = json.loads(next(b.text for b in response.content
                                   if b.type == "text"))
        return VideoMetadata(
            titles=data["titles"][: cfg.claude.title_count],
            hashtags=data["hashtags"],
            hook=data["hook"],
            location_guess=data.get("location_guess"),
            transcript=transcript,
            extra={"usage": {"input": response.usage.input_tokens,
                             "output": response.usage.output_tokens}})
    except anthropic.APIStatusError as e:
        print(f"[metadata] Claude API error {e.status_code}: {e.message} — using fallback")
    except anthropic.APIConnectionError as e:
        print(f"[metadata] connection error: {e} — using fallback")
    except (KeyError, StopIteration, json.JSONDecodeError) as e:
        print(f"[metadata] unexpected response shape: {e} — using fallback")
    return _fallback_metadata(src_name, cfg, transcript)


def cfg_key_present(cfg) -> bool:
    return cfg.anthropic_api_key is not None

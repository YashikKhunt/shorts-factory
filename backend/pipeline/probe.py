"""ffprobe wrapper: everything later stages need to know about an input file."""
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProbeResult:
    duration: float
    width: int              # post-rotation (display) dimensions
    height: int
    fps: float
    has_audio: bool
    is_hdr: bool
    creation_time: str | None = None
    gps: tuple[float, float] | None = None
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0


def _rotation(vstream: dict) -> int:
    for sd in vstream.get("side_data_list", []):
        if "rotation" in sd:
            return int(sd["rotation"])
    return int(vstream.get("tags", {}).get("rotate", 0) or 0)


def _parse_iso6709(s: str) -> tuple[float, float] | None:
    m = re.match(r"([+-]\d+\.?\d*)([+-]\d+\.?\d*)", s)
    return (float(m.group(1)), float(m.group(2))) if m else None


def probe(path: Path) -> ProbeResult:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Could not read video file: {proc.stderr.strip()[:300]}")
    data = json.loads(proc.stdout)

    vstream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if vstream is None:
        raise RuntimeError("File has no video stream")
    astream = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)

    w, h = int(vstream["width"]), int(vstream["height"])
    if abs(_rotation(vstream)) % 180 == 90:
        w, h = h, w

    num, _, den = vstream.get("r_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0

    pix = vstream.get("pix_fmt", "")
    is_hdr = ("10le" in pix or "10be" in pix) and \
        "2020" in (vstream.get("color_primaries", "") + vstream.get("color_space", ""))

    fmt_tags = data.get("format", {}).get("tags", {})
    tags = {**fmt_tags, **vstream.get("tags", {})}
    gps_raw = tags.get("com.apple.quicktime.location.ISO6709") or tags.get("location")

    return ProbeResult(
        duration=float(data["format"].get("duration", 0)),
        width=w, height=h, fps=fps,
        has_audio=astream is not None,
        is_hdr=is_hdr,
        creation_time=tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate"),
        gps=_parse_iso6709(gps_raw) if gps_raw else None,
        raw=data)

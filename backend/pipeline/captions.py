"""Render caption/hook text to transparent PNGs, composited by ffmpeg `overlay`.

This build of ffmpeg has no libass/freetype (no `subtitles`/`drawtext`), so
text is rasterized here with Pillow instead — which also sidesteps all
filtergraph text-escaping issues.
"""
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS_W = 1080
CANVAS_H = 1920
TEXT_MAX_W = int(CANVAS_W * 0.88)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Avenir Next.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux (fonts-dejavu-core)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


@dataclass
class Overlay:
    path: Path
    start: float
    end: float
    y: int          # y position of the image's top edge on the 1080x1920 canvas


def _load_font(size: int, preferred: str | None = None) -> ImageFont.FreeTypeFont:
    candidates = list(FONT_CANDIDATES)
    if preferred:
        candidates.insert(0, f"/System/Library/Fonts/{preferred}.ttc")
    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            try:  # prefer a bold face inside .ttc collections
                font.set_variation_by_name("Bold")
            except OSError:
                pass
            return font
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= TEXT_MAX_W or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render_text_png(text: str, out: Path, font_size: int,
                    font_name: str | None = None) -> Path:
    font = _load_font(font_size, font_name)
    scratch = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap(scratch, text, font)
    line_h = int(font_size * 1.25)
    img = Image.new("RGBA", (CANVAS_W, line_h * len(lines) + 20), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    stroke = max(2, font_size // 14)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        draw.text(((CANVAS_W - w) // 2, 10 + i * line_h), line, font=font,
                  fill=(255, 255, 255, 255), stroke_width=stroke,
                  stroke_fill=(0, 0, 0, 220))
    img.save(out)
    return out


def build_hook_overlay(text: str, cfg, out_dir: Path) -> Overlay:
    png = render_text_png(text, out_dir / "hook.png", font_size=76,
                          font_name=cfg.captions.font)
    return Overlay(path=png, start=0.2, end=0.2 + cfg.hook.duration,
                   y=CANVAS_H // 5)


def build_caption_overlays(segments: list[tuple[float, float, str]],
                           cfg, out_dir: Path) -> list[Overlay]:
    overlays = []
    for i, (start, end, text) in enumerate(segments):
        png = render_text_png(text.strip(), out_dir / f"cap_{i}.png",
                              font_size=cfg.captions.size, font_name=cfg.captions.font)
        with Image.open(png) as im:
            h = im.height
        overlays.append(Overlay(path=png, start=start, end=end,
                                y=CANVAS_H - cfg.captions.bottom_margin - h))
    return overlays

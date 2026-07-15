"""Tests for backend/pipeline/captions.py (Pillow text-overlay rendering)."""
from PIL import ImageDraw, ImageFont

from backend.pipeline import captions as captions_mod


def _default_font(size=32):
    return ImageFont.load_default(size)


class TestWrap:
    def test_short_text_stays_on_one_line(self):
        font = _default_font()
        draw = ImageDraw.Draw(__import__("PIL.Image", fromlist=["Image"]).new("RGBA", (1, 1)))
        lines = captions_mod._wrap(draw, "hi there", font)
        assert lines == ["hi there"]

    def test_long_text_wraps_into_multiple_lines(self):
        font = _default_font(size=60)  # big font forces wraps sooner
        draw = ImageDraw.Draw(__import__("PIL.Image", fromlist=["Image"]).new("RGBA", (1, 1)))
        long_text = " ".join(["word"] * 40)
        lines = captions_mod._wrap(draw, long_text, font)
        assert len(lines) > 1
        # every word must show up somewhere in the wrapped output
        assert sum(len(line.split()) for line in lines) == 40

    def test_empty_text_returns_empty_list(self):
        font = _default_font()
        draw = ImageDraw.Draw(__import__("PIL.Image", fromlist=["Image"]).new("RGBA", (1, 1)))
        assert captions_mod._wrap(draw, "", font) == []

    def test_single_very_long_word_is_not_dropped(self):
        # a single word longer than TEXT_MAX_W must still appear as its own line
        font = _default_font(size=200)
        draw = ImageDraw.Draw(__import__("PIL.Image", fromlist=["Image"]).new("RGBA", (1, 1)))
        lines = captions_mod._wrap(draw, "supercalifragilisticexpialidocious", font)
        assert lines == ["supercalifragilisticexpialidocious"]


class TestRenderTextPng:
    def test_creates_png_with_expected_canvas_width(self, tmp_path):
        out = captions_mod.render_text_png("hello world", tmp_path / "t.png", font_size=40)
        assert out.exists()
        from PIL import Image
        with Image.open(out) as im:
            assert im.width == captions_mod.CANVAS_W
            assert im.mode == "RGBA"

    def test_taller_image_for_multi_line_text(self, tmp_path):
        from PIL import Image
        short = captions_mod.render_text_png("hi", tmp_path / "short.png", font_size=40)
        long_text = " ".join(["reallylongword"] * 30)
        long = captions_mod.render_text_png(long_text, tmp_path / "long.png", font_size=40)
        with Image.open(short) as s, Image.open(long) as l:
            assert l.height > s.height


class TestBuildHookOverlay:
    def test_overlay_timing_and_position(self, cfg, tmp_path, monkeypatch):
        monkeypatch.setattr(captions_mod, "render_text_png",
                            lambda text, out, font_size, font_name=None: out.touch() or out)
        cfg.hook.duration = 2.3
        overlay = captions_mod.build_hook_overlay("Wait for it", cfg, tmp_path)
        assert overlay.start == 0.2
        assert overlay.end == 0.2 + 2.3
        assert overlay.y == captions_mod.CANVAS_H // 5
        assert overlay.path == tmp_path / "hook.png"


class TestBuildCaptionOverlays:
    def test_one_overlay_per_segment_with_correct_timing(self, cfg, tmp_path):
        segments = [(0.0, 1.5, "hello"), (1.5, 3.0, "world")]
        overlays = captions_mod.build_caption_overlays(segments, cfg, tmp_path)
        assert len(overlays) == 2
        assert overlays[0].start == 0.0 and overlays[0].end == 1.5
        assert overlays[1].start == 1.5 and overlays[1].end == 3.0
        for ov in overlays:
            assert ov.path.exists()
            # y position must sit above the configured bottom margin
            assert ov.y < captions_mod.CANVAS_H - cfg.captions.bottom_margin

    def test_empty_segment_list_returns_empty_overlays(self, cfg, tmp_path):
        assert captions_mod.build_caption_overlays([], cfg, tmp_path) == []

    def test_strips_whitespace_from_caption_text(self, cfg, tmp_path, monkeypatch):
        seen = {}

        def _fake_render(text, out, font_size, font_name=None):
            seen["text"] = text
            from PIL import Image
            Image.new("RGBA", (10, 10)).save(out)
            return out

        monkeypatch.setattr(captions_mod, "render_text_png", _fake_render)
        captions_mod.build_caption_overlays([(0.0, 1.0, "  padded text  ")], cfg, tmp_path)
        assert seen["text"] == "padded text"

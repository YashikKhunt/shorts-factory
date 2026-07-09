"""Dev harness: run the full pipeline on one file without the web server.

    .venv/bin/python -m backend.scripts.process_one path/to/clip.mov
"""
import json
import sys
import time
from pathlib import Path

from backend.config import load_settings, startup_checks
from backend.pipeline.runner import process_video


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python -m backend.scripts.process_one <video> [more videos…]")
    cfg = load_settings()
    for w in startup_checks(cfg):
        print(f"[warn] {w}")

    for arg in sys.argv[1:]:
        src = Path(arg).expanduser().resolve()
        if not src.exists():
            print(f"[skip] not found: {src}")
            continue
        t0 = time.time()
        print(f"\n=== {src.name} ===")
        result = process_video(
            src, cfg,
            on_stage=lambda s: print(f"  stage: {s}"),
            on_progress=lambda p: print(f"\r  rendering: {p:5.1f}%", end="", flush=True))
        print(f"\n  done in {time.time() - t0:.1f}s")
        print(json.dumps({k: result[k] for k in
                          ("video", "titles", "hashtags", "hook", "metadata_fallback")},
                         indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

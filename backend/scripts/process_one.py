"""Dev harness: run the full pipeline on one file without the web server.

    .venv/bin/python -m backend.scripts.process_one path/to/clip.mov
    .venv/bin/python -m backend.scripts.process_one --combine a.mov b.mov c.mov
"""
import json
import sys
import time
from pathlib import Path

from backend.config import load_settings, startup_checks
from backend.pipeline.compilation import process_compilation
from backend.pipeline.runner import process_video


def main() -> None:
    args = sys.argv[1:]
    combine = "--combine" in args
    args = [a for a in args if a != "--combine"]
    if not args:
        sys.exit("usage: python -m backend.scripts.process_one [--combine] <video> [more videos…]")
    cfg = load_settings()
    for w in startup_checks(cfg):
        print(f"[warn] {w}")

    if combine and len(args) >= 2:
        srcs = [Path(a).expanduser().resolve() for a in args]
        missing = [s for s in srcs if not s.exists()]
        if missing:
            sys.exit(f"not found: {', '.join(map(str, missing))}")
        t0 = time.time()
        print(f"\n=== combining {len(srcs)} clips ===")
        result = process_compilation(
            srcs, cfg,
            on_stage=lambda s: print(f"  stage: {s}"),
            on_progress=lambda p: print(f"\r  rendering: {p:5.1f}%", end="", flush=True))
        print(f"\n  done in {time.time() - t0:.1f}s")
        print(json.dumps({k: result[k] for k in
                          ("video", "titles", "hook", "clips",
                           "edit_fallback", "metadata_fallback")},
                         indent=2, ensure_ascii=False))
        return

    for arg in args:
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

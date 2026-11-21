"""Command-line entry point: `uv run korvellan-video <command> ...`"""
import argparse
import os
import sys
from pathlib import Path

from .config import load_config


def transcript_for(source: Path, cfg: dict) -> Path:
    """Accept either a transcript.json or the original video; return the transcript path."""
    if source.suffix.lower() == ".json":
        path = source
    else:
        path = cfg["output_dir"] / source.stem / "transcript.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path}\n(Run `korvellan-video transcribe` on the video first.)"
        )
    return path


def main() -> int:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    # Windows terminals default to an old encoding that can't print emoji etc.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="korvellan-video", description="Korvellan Studios video pipeline")
    parser.add_argument("--config", type=Path, help="Path to config.yaml (default: the project's)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="Transcribe a video/audio file with word timestamps")
    p.add_argument("source", type=Path, help="Video or audio file")

    p = sub.add_parser("pick", help="Use the local AI to pick the best clip moments")
    p.add_argument("source", type=Path, help="The video (already transcribed) or its transcript.json")
    p.add_argument("-n", "--max-clips", type=int, help="How many clips to keep (default: from config)")

    p = sub.add_parser("render", help="Cut the picked clips into vertical 9:16 MP4s")
    p.add_argument("source", type=Path, help="The original video (already transcribed and picked)")
    p.add_argument("--layout", choices=["crop", "blur"], help="crop = fill screen, blur = full frame on blurred bg")
    p.add_argument("--only", help="Only these clip ranks, e.g. 1,3,5")

    args = parser.parse_args()
    cfg = load_config(args.config)

    try:
        if args.command == "transcribe":
            from .stages.transcribe import transcribe
            transcribe(args.source, cfg)
        elif args.command == "pick":
            from .stages.pick_moments import pick_moments
            pick_moments(transcript_for(args.source, cfg), cfg, args.max_clips)
        elif args.command == "render":
            from .stages.render import render
            clips_path = cfg["output_dir"] / args.source.stem / "clips.json"
            if not clips_path.exists():
                raise FileNotFoundError(f"{clips_path}\n(Run `korvellan-video pick` on the video first.)")
            only = [int(x) for x in args.only.split(",")] if args.only else None
            render(args.source, clips_path, cfg, args.layout, only)
    except FileNotFoundError as e:
        print(f"Error: file not found: {e.filename or e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

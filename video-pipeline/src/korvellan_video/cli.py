"""Command-line entry point: `uv run korvellan-video <command> ...`"""
import argparse
import os
import sys
from pathlib import Path

from .config import load_config


def main() -> int:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    parser = argparse.ArgumentParser(prog="korvellan-video", description="Korvellan Studios video pipeline")
    parser.add_argument("--config", type=Path, help="Path to config.yaml (default: the project's)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("transcribe", help="Transcribe a video/audio file with word timestamps")
    p.add_argument("source", type=Path, help="Video or audio file")

    args = parser.parse_args()
    cfg = load_config(args.config)

    try:
        if args.command == "transcribe":
            from .stages.transcribe import transcribe
            transcribe(args.source, cfg)
    except FileNotFoundError as e:
        print(f"Error: file not found: {e.filename or e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0

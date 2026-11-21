"""Recipe: long video (file or URL) -> captioned vertical clips.

download (if URL) -> transcribe -> pick -> render

Finished steps are reused: if the transcript or picks already exist they're
skipped, so re-running is fast. Use `redo` to force steps to run again.
"""
import time
from pathlib import Path

from ..stages.download import download, is_url
from ..stages.pick_moments import pick_moments
from ..stages.render import render
from ..stages.transcribe import transcribe


def banner(step: int, total: int, text: str) -> None:
    print(f"\n=== Step {step}/{total}: {text} " + "=" * max(0, 50 - len(text)))


def clipper(source: str, cfg: dict, max_clips: int | None = None, layout: str | None = None,
            captions: bool | None = None, redo: set[str] | None = None) -> Path:
    redo = redo or set()
    started = time.time()
    total = 4 if is_url(source) else 3
    step = 0

    if is_url(source):
        step += 1
        banner(step, total, "Download")
        video = download(source, cfg)
    else:
        video = Path(source)
        if not video.exists():
            raise FileNotFoundError(video)

    work_dir = cfg["output_dir"] / video.stem
    transcript_path = work_dir / "transcript.json"
    clips_path = work_dir / "clips.json"

    step += 1
    banner(step, total, "Transcribe")
    if transcript_path.exists() and "transcribe" not in redo:
        print(f"Already transcribed, reusing {transcript_path.name}")
    else:
        transcript_path = transcribe(video, cfg)

    step += 1
    banner(step, total, "Pick best moments")
    if clips_path.exists() and "pick" not in redo and max_clips is None:
        print(f"Already picked, reusing {clips_path.name} (use --redo pick for fresh picks)")
    else:
        clips_path = pick_moments(transcript_path, cfg, max_clips)

    step += 1
    banner(step, total, "Render clips")
    out_dir = render(video, clips_path, cfg, layout, None, captions)

    mins, secs = divmod(int(time.time() - started), 60)
    print(f"\nAll done in {mins}m {secs:02d}s. Your clips are in:\n  {out_dir}")
    return out_dir

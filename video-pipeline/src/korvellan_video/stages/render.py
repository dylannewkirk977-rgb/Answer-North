"""Stage: cut the picked clips out of the source video as vertical (9:16) MP4s.

Input:  the source video + <output_dir>/<video name>/clips.json (+ transcript.json for captions)
Output: <output_dir>/<video name>/clips/01-<title>.mp4 (+ 01-<title>.ass caption file)
        <output_dir>/<video name>/layout.json (which layout was used and why)

Layouts (see stages/layout.py for how `auto` decides):
- split: face cam enlarged on top, gameplay below. For streamers with a face cam.
- crop:  a vertical slice centered on the person. For one person on camera.
- blur:  the full wide frame over a blurred zoomed copy of itself. Nothing is cut off.
- auto:  picks one of the above per video.

Captions are burned in during the same encode (no second render).
"""
import json
import re
import subprocess
import time
from pathlib import Path

from ..media import ffmpeg_path
from .captions import build_ass
from .layout import OUT_H as H
from .layout import OUT_W as W
from .layout import SPLIT_TOP_H, plan_layout, save_plan

LAYOUTS = ("auto", "split", "crop", "blur")


def layout_filter(plan: dict) -> str:
    """ffmpeg filter that turns the source frame into a 1080x1920 frame."""
    layout = plan["layout"]
    src_h = plan["source_size"][1]
    if layout == "split":
        x, y, cw, ch = plan["facecam"]
        return (
            "split[c][g];"
            f"[c]crop={cw}:{ch}:{x}:{y},scale={W}:{SPLIT_TOP_H}:flags=lanczos,setsar=1[top];"
            f"[g]crop={plan['gameplay_w']}:{src_h}:{plan['gameplay_x']}:0,"
            f"scale={W}:{H - SPLIT_TOP_H}:flags=lanczos,setsar=1[bot];"
            "[top][bot]vstack,setsar=1"
        )
    if layout == "crop":
        return f"crop={plan['crop_w']}:{src_h}:{plan['crop_x']}:0,scale={W}:{H}:flags=lanczos,setsar=1"
    # blur: blur a small copy (fast), scale it up as the background, overlay the full frame.
    return (
        "split[bg][fg];"
        f"[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
        f"boxblur=8:2,scale={W}:{H}[bgb];"
        f"[fg]scale={W}:-2:flags=lanczos[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def slugify(text: str, max_len: int = 50) -> str:
    """Make a title safe for a Windows file name (letters, numbers, dashes)."""
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "clip"


def render_clip(source: Path, start: float, end: float, out_path: Path, vf: str,
                rcfg: dict, ass_path: Path | None = None) -> None:
    if ass_path:
        # ffmpeg's filter syntax chokes on Windows paths ("C:"), so we run ffmpeg
        # inside the clip folder and refer to the caption file by name only.
        vf += f",ass={ass_path.name}"
    cmd = [
        ffmpeg_path(), "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(source.resolve()), "-t", f"{end - start:.3f}",
        "-filter_complex", vf,
        "-c:v", rcfg.get("video_encoder", "h264_nvenc"),
        "-preset", "p5", "-rc", "vbr", "-cq", str(rcfg.get("quality", 23)), "-b:v", "0",
        # Cap the bitrate: uncapped, 1080x1920@60 game footage hits ~19 Mbps (~120 MB per 50 s).
        "-maxrate", f"{rcfg.get('max_mbps', 10)}M", "-bufsize", f"{2 * rcfg.get('max_mbps', 10)}M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path.resolve()),
    ]
    result = subprocess.run(cmd, capture_output=True, cwd=out_path.parent)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {out_path.name}:\n{result.stderr.decode(errors='replace')[-1500:]}")


def render(source: Path, clips_path: Path, cfg: dict, layout: str | None = None,
           only: list[int] | None = None, captions: bool | None = None) -> Path:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    rcfg = cfg.get("render", {})
    ccfg = cfg.get("captions", {})
    layout = layout or rcfg.get("layout", "auto")
    if layout not in LAYOUTS:
        raise RuntimeError(f"Unknown layout '{layout}'. Choose: {', '.join(LAYOUTS)}")
    if captions is None:
        captions = bool(ccfg.get("enabled", True))

    clips_path = Path(clips_path)
    clips = json.loads(clips_path.read_text(encoding="utf-8"))["clips"]
    if only:
        clips = [c for c in clips if c["rank"] in only]
    if not clips:
        raise RuntimeError("No clips to render (check clips.json or --only).")

    segments = []
    if captions:
        transcript_path = clips_path.parent / "transcript.json"
        segments = json.loads(transcript_path.read_text(encoding="utf-8"))["segments"]

    if layout != "blur":
        print(f"Choosing layout ('{layout}')...")
    plan = plan_layout(source, cfg, layout)
    save_plan(plan, clips_path.parent / "layout.json")
    print(f"  Layout: {plan['layout']} ({plan['reason']})")
    vf = layout_filter(plan)

    out_dir = clips_path.parent / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {len(clips)} clip(s) from {source.name} as 9:16 '{plan['layout']}'"
          f"{' with captions' if captions else ''} -> {out_dir}")

    started = time.time()
    for c in clips:
        name = f"{c['rank']:02d}-{slugify(c['title'])}"
        out_path = out_dir / f"{name}.mp4"
        ass_path = None
        if captions:
            ass_path = out_dir / f"{name}.ass"
            build_ass(segments, c["start"], c["end"], ass_path, ccfg, W, H, plan["layout"])
        t0 = time.time()
        render_clip(source, c["start"], c["end"], out_path, vf, rcfg, ass_path)
        size_mb = out_path.stat().st_size / 1e6
        print(f"  #{c['rank']:<2} {c['duration']:>4.0f}s -> {out_path.name} "
              f"({size_mb:.1f} MB, {time.time() - t0:.0f}s)")

    print(f"Done in {time.time() - started:.0f}s. Open the folder:\n  {out_dir}")
    return out_dir

"""Stage: cut the picked clips out of the source video as vertical (9:16) MP4s.

Input:  the source video + <output_dir>/<video name>/clips.json
Output: <output_dir>/<video name>/clips/01-<title>.mp4, 02-..., ...

Layouts:
- crop: a vertical slice from the center of the frame. Fills the screen, but the
        sides are cut off. Best for one person centered on camera.
- blur: the full wide frame in the middle, over a blurred zoomed copy of itself.
        Nothing is cut off. Best for gameplay and screen content.
"""
import json
import re
import subprocess
import time
from pathlib import Path

from ..media import ffmpeg_path

W, H = 1080, 1920  # vertical 1080p

LAYOUT_FILTERS = {
    "crop": f"crop=ih*9/16:ih,scale={W}:{H}:flags=lanczos,setsar=1",
    # Blur a small copy (fast), scale it up as the background, overlay the full frame.
    "blur": (
        "split[bg][fg];"
        f"[bg]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
        f"boxblur=8:2,scale={W}:{H}[bgb];"
        f"[fg]scale={W}:-2:flags=lanczos[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
    ),
}


def slugify(text: str, max_len: int = 50) -> str:
    """Make a title safe for a Windows file name (letters, numbers, dashes)."""
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:max_len].rstrip("-") or "clip"


def render_clip(source: Path, start: float, end: float, out_path: Path, layout: str, rcfg: dict) -> None:
    cmd = [
        ffmpeg_path(), "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{end - start:.3f}",
        "-filter_complex", LAYOUT_FILTERS[layout],
        "-c:v", rcfg.get("video_encoder", "h264_nvenc"),
        "-preset", "p5", "-rc", "vbr", "-cq", str(rcfg.get("quality", 23)), "-b:v", "0",
        # Cap the bitrate: uncapped, 1080x1920@60 game footage hits ~19 Mbps (~120 MB per 50 s).
        "-maxrate", f"{rcfg.get('max_mbps', 10)}M", "-bufsize", f"{2 * rcfg.get('max_mbps', 10)}M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {out_path.name}:\n{result.stderr.decode(errors='replace')[-1500:]}")


def render(source: Path, clips_path: Path, cfg: dict, layout: str | None = None,
           only: list[int] | None = None) -> Path:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    rcfg = cfg.get("render", {})
    layout = layout or rcfg.get("layout", "blur")
    if layout not in LAYOUT_FILTERS:
        raise RuntimeError(f"Unknown layout '{layout}'. Choose: {', '.join(LAYOUT_FILTERS)}")

    clips = json.loads(Path(clips_path).read_text(encoding="utf-8"))["clips"]
    if only:
        clips = [c for c in clips if c["rank"] in only]
    if not clips:
        raise RuntimeError("No clips to render (check clips.json or --only).")

    out_dir = Path(clips_path).parent / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Rendering {len(clips)} clip(s) from {source.name} as 9:16 '{layout}' -> {out_dir}")

    started = time.time()
    for c in clips:
        suffix = f"-{layout}" if only else ""
        out_path = out_dir / f"{c['rank']:02d}-{slugify(c['title'])}{suffix}.mp4"
        t0 = time.time()
        render_clip(source, c["start"], c["end"], out_path, layout, rcfg)
        size_mb = out_path.stat().st_size / 1e6
        print(f"  #{c['rank']:<2} {c['duration']:>4.0f}s -> {out_path.name} "
              f"({size_mb:.1f} MB, {time.time() - t0:.0f}s)")

    print(f"Done in {time.time() - started:.0f}s. Open the folder:\n  {out_dir}")
    return out_dir

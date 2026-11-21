"""Stage: download a video (YouTube etc.) into the input folder with yt-dlp.

Only download footage you have the rights to use: your own, a client's, or
Creative Commons / public domain.
"""
import shutil
import subprocess
from pathlib import Path

from ..media import ffmpeg_path


def is_url(text: str) -> bool:
    return str(text).lower().startswith(("http://", "https://", "www.", "youtu.be/", "youtube.com/"))


def download(url: str, cfg: dict) -> Path:
    exe = shutil.which("yt-dlp")
    if not exe:
        raise RuntimeError("yt-dlp not found. Install it with: uv tool install yt-dlp "
                           "(then reopen the terminal).")
    input_dir = cfg["input_dir"]
    input_dir.mkdir(parents=True, exist_ok=True)
    height = int(cfg.get("download", {}).get("max_height", 1080))

    cmd = [
        exe, url,
        "--no-playlist",
        "-f", f"bv*[height<={height}]+ba/b[height<={height}]/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", str(Path(ffmpeg_path()).parent),
        # Title-based name, trimmed so Windows paths stay short.
        "-o", str(input_dir / "%(title).80B.%(ext)s"),
        # Print the final file path at the end (and still show the progress bar).
        "--print", "after_move:filepath", "--progress", "--no-simulate",
    ]
    print(f"Downloading {url} (up to {height}p) into {input_dir} ...")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError("yt-dlp failed (see messages above). Check the link, or update yt-dlp "
                           "with: uv tool upgrade yt-dlp")

    lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
    if not lines or not Path(lines[-1]).exists():
        raise RuntimeError(f"Download finished but the file wasn't found. yt-dlp said:\n{result.stdout[-500:]}")
    path = Path(lines[-1])
    print(f"Saved {path}")
    return path

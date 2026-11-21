"""ffmpeg helpers."""
import shutil
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000  # what Whisper expects


def ffmpeg_path() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError(
            "ffmpeg not found on PATH. If it was just installed, close and reopen "
            "the terminal (or restart VS Code) so the new PATH is picked up."
        )
    return exe


def probe_video(path: Path) -> tuple[int, int, float]:
    """Return (width, height, duration_seconds) of a video file."""
    ffprobe = str(Path(ffmpeg_path()).with_name("ffprobe" + Path(ffmpeg_path()).suffix))
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height:format=duration", "-of", "default=nw=1", str(path)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe could not read {path}:\n{out.stderr}")
    info = dict(line.split("=", 1) for line in out.stdout.split() if "=" in line)
    return int(info["width"]), int(info["height"]), float(info["duration"])


def grab_frame(path: Path, t: float, width: int, height: int) -> np.ndarray | None:
    """One video frame at time t, resized, as a BGR image (OpenCV format)."""
    cmd = [ffmpeg_path(), "-nostdin", "-v", "error", "-ss", f"{t:.2f}", "-i", str(path),
           "-frames:v", "1", "-vf", f"scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    if len(raw) != width * height * 3:
        return None
    return np.frombuffer(raw, np.uint8).reshape(height, width, 3)


def load_audio(path: Path) -> np.ndarray:
    """Decode any audio/video file to 16 kHz mono float32 samples using ffmpeg."""
    cmd = [
        ffmpeg_path(), "-nostdin", "-v", "error",
        "-i", str(path),
        "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg could not read {path}:\n{result.stderr.decode(errors='replace')}")
    return np.frombuffer(result.stdout, np.float32)

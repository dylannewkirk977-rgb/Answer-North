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

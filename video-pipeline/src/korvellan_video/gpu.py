"""Make NVIDIA's CUDA libraries (installed as pip packages) findable on Windows.

faster-whisper needs cuBLAS and cuDNN. We install them into the project's .venv
(nvidia-cublas-cu12, nvidia-cudnn-cu12), but Windows won't look in those folders
on its own, so this must run before faster_whisper is imported.
"""
import os
import sys
from pathlib import Path

_done = False


def setup_cuda_dlls() -> None:
    global _done
    if _done or sys.platform != "win32":
        return
    nvidia_dir = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    bin_dirs = [str(p) for p in nvidia_dir.glob("*/bin") if p.is_dir()]
    for d in bin_dirs:
        os.add_dll_directory(d)
    # Some libraries are loaded by name through PATH, so add them there too.
    os.environ["PATH"] = os.pathsep.join(bin_dirs + [os.environ.get("PATH", "")])
    _done = True

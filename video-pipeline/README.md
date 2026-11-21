# Video Pipeline

Automated video production for Korvellan Studios.

- **Clipper** (in progress): long video → best moments → captioned vertical clips
- **Faceless** (planned): topic → script → voiceover → visuals → video

## Setup

```powershell
cd video-pipeline
uv sync
```

This installs everything into `.venv`, including NVIDIA's GPU libraries (~2 GB). ffmpeg must be on PATH (`winget install Gyan.FFmpeg`).

## Getting test videos

Put source videos in `input/` (not committed). Only use footage you have rights to: Creative Commons, your own, or a client's.

```powershell
yt-dlp -f "bv*[height<=1080]+ba/b" --merge-output-format mp4 -o "input\%(title)s.%(ext)s" "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Usage

```powershell
uv run korvellan-video transcribe "input\video.mp4"
```

Writes `output/<video name>/transcript.json` with word-level timestamps. The first run downloads the Whisper model (~1.6 GB for `large-v3-turbo`).

Settings (models, GPU, output folder) are in [config.yaml](config.yaml). Use `--config other.yaml` to try different settings.

## Layout

```
config.yaml               settings
src/korvellan_video/
  cli.py                  commands
  config.py               loads config.yaml
  gpu.py                  makes NVIDIA libraries findable on Windows
  media.py                ffmpeg helpers
  stages/transcribe.py    Whisper transcription
output/                   results (not committed)
```

## Notes
- Each run starts with a ~10 s GPU warm-up. After that, transcription runs at roughly 30× real time on the RTX 5070.
- Audio is decoded with ffmpeg rather than faster-whisper's built-in reader: the bundled PyAV 19 is incompatible with faster-whisper 1.2.1.
- `nvidia-cublas-cu12` is capped below 12.9.3 because that release has no Windows build.

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

```powershell
uv run korvellan-video pick "input\video.mp4"          # or -n 5 for top 5
```

The local AI (Ollama) reads the transcript and writes `output/<video name>/clips.json`: the best 20–60 s moments, ranked, with title, hook, and reason. Needs the Ollama app running. Takes ~2.5 min for a 48-min video.

```powershell
uv run korvellan-video render "input\video.mp4"                  # all picked clips
uv run korvellan-video render "input\video.mp4" --only 1,3 --layout crop
```

Cuts each pick into a 1080×1920 MP4 in `output/<video name>/clips/`, encoded on the RTX 5070 (~10 s per clip). Layouts: `blur` (full frame over a blurred background; keeps face cams and HUD, the default) or `crop` (center slice; fills the screen, cuts the sides).

How picking works: the transcript is read in 5-minute overlapping chunks, and the AI suggests up to 3 clips per chunk. Code snaps them to whole sentences, enforces length limits, and removes duplicates. A final pass shows the AI all candidates together and it chooses the top N in order. Tune it in the `clipper:` section of `config.yaml` (add `style_notes` to describe a channel).

Settings (models, GPU, output folder) are in [config.yaml](config.yaml). Use `--config other.yaml` to try different settings.

## Layout

```
config.yaml               settings
src/korvellan_video/
  cli.py                  commands
  config.py               loads config.yaml
  gpu.py                  makes NVIDIA libraries findable on Windows
  media.py                ffmpeg helpers
  llm.py                  Ollama client (JSON replies)
  stages/transcribe.py    Whisper transcription
  stages/pick_moments.py  AI clip picking
  stages/render.py        cut + 9:16 layout + GPU encode
output/                   results (not committed)
```

## Notes
- Each run starts with a ~10 s GPU warm-up. After that, transcription runs at roughly 30× real time on the RTX 5070.
- Audio is decoded with ffmpeg rather than faster-whisper's built-in reader: the bundled PyAV 19 is incompatible with faster-whisper 1.2.1.
- `nvidia-cublas-cu12` is capped below 12.9.3 because that release has no Windows build.
- The picker uses Ollama's native API (not `/v1`) so it can raise the context size (Ollama's default is small and silently truncates) and enforce a JSON schema.
- The 9B model inflates scores and stops partway through long lists, so the final ranking asks it to *choose and order* the top N rather than score every candidate.

# Video Pipeline

Automated video production for Korvellan Studios.

- **Clipper** (working): long video → best moments → captioned vertical clips
- **Faceless** (planned): topic → script → voiceover → visuals → video

## Setup

```powershell
cd video-pipeline
uv sync
```

This installs everything into `.venv`, including NVIDIA's GPU libraries (~2 GB). Also needed on PATH: ffmpeg (`winget install Gyan.FFmpeg`) and yt-dlp (`uv tool install yt-dlp`). The Ollama app must be running for clip picking.

Only use footage you have rights to: your own, a client's, or Creative Commons / public domain.

## Quick start: one command

```powershell
uv run korvellan-video clipper "https://www.youtube.com/watch?v=..."   # a link...
uv run korvellan-video clipper "input\video.mp4"                       # ...or a file
```

Runs download (for links) → transcribe → pick → render. Clips land in `output/<video name>/clips/`. Steps that already finished are reused, so re-running only re-renders. Options:

- `-n 5`: number of clips (re-picks if given)
- `--layout crop`: fill the screen instead of the default `blur`
- `--no-captions`: skip captions
- `--redo pick` / `--redo transcribe`: force a step to run again (e.g. fresh picks)

## Individual steps

```powershell
uv run korvellan-video download "https://www.youtube.com/watch?v=..."   # -> input/
uv run korvellan-video transcribe "input\video.mp4"
uv run korvellan-video pick "input\video.mp4"          # or -n 5 for top 5
uv run korvellan-video render "input\video.mp4"        # or --only 1,3 --layout crop
```

- **download**: saves to `input/` as `<title>.mp4`, up to 1080p (`download.max_height`).
- **transcribe**: writes `output/<video name>/transcript.json` with word-level timestamps. The first run downloads the Whisper model (~1.6 GB for `large-v3-turbo`).
- **pick**: the local AI (Ollama) reads the transcript and writes `clips.json`: the best 20–60 s moments, ranked, with title, hook, and reason. ~2.5 min for a 48-min video.
- **render**: cuts each pick into a 1080×1920 MP4 in `clips/`, encoded on the RTX 5070 (~10 s per clip). Word-by-word captions (spoken word highlighted) are burned in during the same encode; style them in the `captions:` section of `config.yaml`. Each clip's `.ass` caption file is saved next to it and can be hand-edited (e.g. in Aegisub) and re-rendered. Layouts: `blur` (full frame over a blurred background; keeps face cams and HUD, the default) or `crop` (center slice; fills the screen, cuts the sides).

How picking works: the transcript is read in 5-minute overlapping chunks, and the AI suggests up to 3 clips per chunk. Code snaps them to whole sentences, enforces length limits, and removes duplicates. A final pass shows the AI all candidates together and it chooses the top N in order. Tune it in the `clipper:` section of `config.yaml` (add `style_notes` to describe a channel).

Settings (models, GPU, folders, caption style) are in [config.yaml](config.yaml). Use `--config other.yaml` to try different settings.

## Layout

```
config.yaml               settings
src/korvellan_video/
  cli.py                  commands
  config.py               loads config.yaml
  gpu.py                  makes NVIDIA libraries findable on Windows
  media.py                ffmpeg helpers
  llm.py                  Ollama client (JSON replies)
  stages/download.py      yt-dlp download
  stages/transcribe.py    Whisper transcription
  stages/pick_moments.py  AI clip picking
  stages/render.py        cut + 9:16 layout + GPU encode
  stages/captions.py      word-by-word .ass captions
  recipes/clipper.py      download → transcribe → pick → render
input/                    source videos (not committed)
output/                   results (not committed)
```

## Notes
- Each run starts with a ~10 s GPU warm-up. After that, transcription runs at roughly 30× real time on the RTX 5070.
- Audio is decoded with ffmpeg rather than faster-whisper's built-in reader: the bundled PyAV 19 is incompatible with faster-whisper 1.2.1.
- `nvidia-cublas-cu12` is capped below 12.9.3 because that release has no Windows build.
- The picker uses Ollama's native API (not `/v1`) so it can raise the context size (Ollama's default is small and silently truncates) and enforce a JSON schema.
- The 9B model inflates scores and stops partway through long lists, so the final ranking asks it to *choose and order* the top N rather than score every candidate.
- yt-dlp warns that it has no JavaScript runtime for YouTube. Downloads work for now, but YouTube may require one (deno) in future.

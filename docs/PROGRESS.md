# Progress

## Current focus
Local AI environment, then an automated video production pipeline.

## Done
- **2026-11-20**: Assessed the dev environment (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-20**: Rebranded the repo from Answer North to Korvellan Studios; added project docs.
- **2026-11-20**: Renamed the local folder to `Korvellan-Studios` and the GitHub repo to `Korvellan-Studios`.
- **2026-11-21**: Chose the first video products: **short vertical clips** and **faceless videos**.
- **2026-11-21**: Installed ffmpeg 9.1 (winget). Verified NVIDIA hardware encoding (h264/hevc/av1_nvenc) on the RTX 5070.

- **2026-11-21**: Agreed on the video pipeline design: one `video-pipeline/` project, shared stages, Clipper recipe first (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-21**: Created `video-pipeline/` with the **transcribe** stage: faster-whisper on the RTX 5070 (~30× real time), word-level timestamps → `transcript.json`. Tested end-to-end on a generated test video.

- **2026-11-21**: Installed yt-dlp for test footage; added `video-pipeline/input/` (gitignored) for source videos.

- **2026-11-21**: Transcribed a real 48-min gaming video: 92% avg word confidence, ~3 min.
- **2026-11-21**: Built the **pick** stage: local LLM (qwen3.5:9b) picks and ranks the top 10 clips (20–60 s) → `clips.json`. ~2.5 min for a 48-min video.

## Next
1. Render stage: cut each clip, crop to 9:16, encode on the GPU → vertical MP4s.
2. Captions: burned-in, word-by-word, from the word timestamps.
3. `clipper` recipe: one command runs transcribe → pick → render.
4. Later: loudness detection to catch non-verbal moments (screams, big plays) in gaming content.

## Waiting on
- **Radeon AI PRO R9700**: needs an 8-pin adapter for clearance before install. After install: AMD driver, verify detection, move LLM work onto it.

## Known issues
- **prospect-finder**:
  - `--industry` is not used in the search query, so it returns all shops in the city.
  - The city match is exact and case-sensitive ("STILLWATER" won't match "Stillwater").
  - `fetch_location()` is defined but never called.

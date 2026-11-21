# Progress

## Current focus
Video pipeline: the **Clipper** (long video → captioned vertical clips) works end-to-end. Next: test on better source material, then polish.

## Done
- **2026-11-20**: Assessed the dev environment (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-20**: Rebranded the repo from Answer North to Korvellan Studios; added project docs.
- **2026-11-20**: Renamed the local folder to `Korvellan-Studios` and the GitHub repo to `Korvellan-Studios`.
- **2026-11-21**: Chose the first video products: **short vertical clips** and **faceless videos**.
- **2026-11-21**: Installed ffmpeg 9.1 (winget). Verified NVIDIA hardware encoding (h264/hevc/av1_nvenc) on the RTX 5070.
- **2026-11-21**: Agreed on the video pipeline design: one `video-pipeline/` project, shared stages, Clipper recipe first (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-21**: Built the **transcribe** stage: faster-whisper on the RTX 5070 (~30× real time), word-level timestamps → `transcript.json`.
- **2026-11-21**: Installed yt-dlp; added `video-pipeline/input/` (gitignored) for source videos.
- **2026-11-21**: Transcribed a real 48-min gaming video: 92% avg word confidence, ~3 min.
- **2026-11-21**: Built the **pick** stage: local LLM (qwen3.5:9b) picks and ranks the top 10 clips (20–60 s) → `clips.json`. ~2.5 min for a 48-min video.
- **2026-11-21**: Built the **render** stage: picks → 1080×1920 MP4s on NVENC (~10 s/clip, ~10 Mbps). Layouts: `blur` (user's choice) and `crop`.
- **2026-11-21**: Built **captions**: word-by-word, spoken word highlighted yellow, burned in during render. Font size 100, max 16 chars per caption.
- **2026-11-21**: Built **`clipper`** (one command: link or file → download → transcribe → pick → render, reusing finished steps) and **`download`** (yt-dlp into `input/`). Tested end-to-end from a YouTube link: all 10 captioned clips in 1m 39s.

## Feedback so far
- Test video: timestamps were decent, but the source itself is low-energy. Need a livelier Creative Commons podcast/interview.
- No caption censoring for now (user's call).

## Next
1. Test on a livelier Creative Commons podcast/interview.
2. Consider installing deno: yt-dlp warns that YouTube extraction without a JavaScript runtime is deprecated.
3. Later: `split` layout (face cam on top, gameplay below) for streamer content.
4. Later: loudness detection to catch non-verbal moments (screams, big plays) in gaming content.
5. Later: optional caption censoring.

## Waiting on
- **Radeon AI PRO R9700**: needs an 8-pin adapter for clearance before install. After install: AMD driver, verify detection, move LLM work onto it.

## Known issues
- **prospect-finder**:
  - `--industry` is not used in the search query, so it returns all shops in the city.
  - The city match is exact and case-sensitive ("STILLWATER" won't match "Stillwater").
  - `fetch_location()` is defined but never called.

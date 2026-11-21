# Progress

## Current focus
Local AI environment, then an automated video production pipeline.

## Done
- **2026-11-20**: Assessed the dev environment (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-20**: Rebranded the repo from Answer North to Korvellan Studios; added project docs.
- **2026-11-20**: Renamed the local folder to `Korvellan-Studios` and the GitHub repo to `Korvellan-Studios`.
- **2026-11-21**: Chose the first video products: **short vertical clips** and **faceless videos**.
- **2026-11-21**: Installed ffmpeg 9.1 (winget). Verified NVIDIA hardware encoding (h264/hevc/av1_nvenc) on the RTX 5070.

## Next
1. Agree on the video pipeline design.
2. Build the shared foundation: transcription, captions, vertical render.

## Waiting on
- **Radeon AI PRO R9700**: needs an 8-pin adapter for clearance before install. After install: AMD driver, verify detection, move LLM work onto it.

## Known issues
- **prospect-finder**:
  - `--industry` is not used in the search query, so it returns all shops in the city.
  - The city match is exact and case-sensitive ("STILLWATER" won't match "Stillwater").
  - `fetch_location()` is defined but never called.

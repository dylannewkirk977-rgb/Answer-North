# Progress

## Current focus
Local AI environment, then an automated video production pipeline.

## Done
- **2026-11-20**: Assessed the dev environment (see [ARCHITECTURE.md](ARCHITECTURE.md)).
- **2026-11-20**: Rebranded the repo from Answer North to Korvellan Studios; added project docs.

## Next
1. Rename the local folder (and optionally the GitHub repo) to `korvellan-studios`.
2. Decide the first video product (format, length, style).
3. Install ffmpeg.
4. Build the video pipeline skeleton: topic → script → voiceover → captions → MP4.

## Waiting on
- **Radeon AI PRO R9700**: needs an 8-pin adapter for clearance before install. After install: AMD driver, verify detection, move LLM work onto it.

## Known issues
- **prospect-finder**:
  - `--industry` is not used in the search query, so it returns all shops in the city.
  - The city match is exact and case-sensitive ("STILLWATER" won't match "Stillwater").
  - `fetch_location()` is defined but never called.

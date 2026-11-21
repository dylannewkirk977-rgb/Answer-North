"""Stage: transcribe a video/audio file to text with word-level timestamps.

Output: <output_dir>/<video name>/transcript.json
"""
import json
import time
from pathlib import Path

from ..gpu import setup_cuda_dlls
from ..media import SAMPLE_RATE, load_audio


def transcribe(source: Path, cfg: dict) -> Path:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    tcfg = cfg["transcribe"]

    setup_cuda_dlls()
    from faster_whisper import WhisperModel  # import after DLL setup

    print(f"Decoding audio from {source.name}...")
    audio = load_audio(source)
    duration = len(audio) / SAMPLE_RATE
    print(f"  {duration / 60:.1f} minutes of audio")

    print(f"Loading Whisper '{tcfg['model']}' on {tcfg['device']} "
          "(first run downloads the model)...")
    model = WhisperModel(tcfg["model"], device=tcfg["device"], compute_type=tcfg["compute_type"])

    print("Transcribing...")
    started = time.time()
    segments_iter, info = model.transcribe(
        audio,
        language=tcfg.get("language"),
        hotwords=tcfg.get("hotwords") or None,
        word_timestamps=True,
        vad_filter=True,  # skip long silences
    )

    segments = []
    for seg in segments_iter:
        segments.append({
            "start": round(seg.start, 3),
            "end": round(seg.end, 3),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 3), "end": round(w.end, 3),
                 "word": w.word.strip(), "probability": round(w.probability, 3)}
                for w in (seg.words or [])
            ],
        })
        pct = min(100, seg.end / duration * 100) if duration else 100
        print(f"  [{pct:5.1f}%] {seg.text.strip()[:80]}")

    elapsed = time.time() - started
    out_dir = cfg["output_dir"] / source.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "transcript.json"
    out_path.write_text(json.dumps({
        "source": str(source.resolve()),
        "language": info.language,
        "duration": round(duration, 3),
        "model": tcfg["model"],
        "segments": segments,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    speed = duration / elapsed if elapsed else 0
    print(f"Done: {len(segments)} segments in {elapsed:.0f}s ({speed:.0f}x real time)")
    print(f"Saved {out_path}")
    return out_path

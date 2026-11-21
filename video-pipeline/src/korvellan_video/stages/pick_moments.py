"""Stage: have the local LLM pick the best short-clip moments from a transcript.

Input:  <output_dir>/<video name>/transcript.json
Output: <output_dir>/<video name>/clips.json

How it works:
1. Split the transcript into overlapping chunks (a few minutes each).
2. For each chunk, the LLM picks candidate clips by line number, with a title,
   hook, reason, and 1-10 score.
3. Code (not the LLM) enforces the rules: snap to whole lines, fit the length
   limits, drop overlapping picks.
4. Ranking pass: the LLM sees all remaining candidates side by side and picks
   the top N, best first. (Per-chunk scores are inflated, since every chunk's
   best moment looks like a 9, so the final order comes from this comparison.)
"""
import json
import time
from datetime import datetime
from pathlib import Path

from ..llm import chat_json

PAD_BEFORE = 0.3  # seconds of breathing room before the first word
PAD_AFTER = 0.6   # ...and after the last word

SYSTEM_PROMPT = """You are an expert short-form video editor. You find the moments in long videos \
that will perform best as standalone vertical clips (TikTok, Reels, YouTube Shorts).

A great clip:
- Hooks the viewer in the first 3 seconds (a bold statement, question, reaction, or surprise).
- Makes sense on its own, without the rest of the video.
- Has a payoff: a punchline, insight, reveal, or strong emotional peak, and ends right after it.
- Is {min_s}-{max_s} seconds long.

Be selective. Only pick moments you'd genuinely post. If nothing in this part is clip-worthy, \
return an empty list. Score honestly: 9-10 = likely viral, 7-8 = strong, 5-6 = okay, below 5 = skip.
{style}"""

USER_PROMPT = """Here is part of a transcript. Each line is: #line_number [mm:ss] text

{lines}

Pick up to 3 clips from this part. For each clip give:
- start_line / end_line: line numbers from above (inclusive). Aim for {min_s}-{max_s} seconds.
- title: catchy, under 60 characters, for the clip's caption
- hook: the opening words that grab attention
- reason: one sentence on why it works
- score: 1-10"""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                },
                "required": ["start_line", "end_line", "title", "hook", "reason", "score"],
            },
        }
    },
    "required": ["clips"],
}


RANK_PROMPT = """Below are {n} candidate clips from the same video, found separately. \
Compare them against EACH OTHER and choose the {k} that would perform best as standalone \
shorts: strongest hook, makes sense without context, clear payoff.

{items}

Return the ids of your top {k}, best first."""

RANK_SCHEMA = {
    "type": "object",
    "properties": {"best_ids": {"type": "array", "items": {"type": "integer"}}},
    "required": ["best_ids"],
}

DUPLICATE_OVERLAP = 0.1  # clips sharing more than 10% of the shorter one count as the same moment


def fmt_time(t: float) -> str:
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def make_chunks(segments: list[dict], chunk_s: float, overlap_s: float) -> list[tuple[int, int]]:
    """Return (first_index, last_index) ranges covering the transcript with overlap."""
    chunks = []
    if not segments:
        return chunks
    start_i = 0
    while start_i < len(segments):
        window_end = segments[start_i]["start"] + chunk_s
        end_i = start_i
        while end_i + 1 < len(segments) and segments[end_i + 1]["start"] < window_end:
            end_i += 1
        chunks.append((start_i, end_i))
        if end_i == len(segments) - 1:
            break
        # Next chunk starts `overlap_s` before this one ended (but always moves forward).
        next_i = end_i
        while next_i > start_i + 1 and segments[next_i]["start"] > segments[end_i]["end"] - overlap_s:
            next_i -= 1
        start_i = max(next_i, start_i + 1)
    return chunks


def fit_length(segments: list[dict], s: int, e: int, min_s: float, max_s: float):
    """Adjust a clip (by whole lines) to fit the length limits. Returns (s, e) or None."""
    def dur(a, b):
        return segments[b]["end"] - segments[a]["start"]

    while dur(s, e) > max_s and e > s:         # too long: trim the end
        e -= 1
    while dur(s, e) < min_s:                     # too short: extend
        if e + 1 < len(segments) and dur(s, e + 1) <= max_s:
            e += 1
        elif s > 0 and dur(s - 1, e) <= max_s:
            s -= 1
        else:
            break
    d = dur(s, e)
    return (s, e) if min_s <= d <= max_s else None


def overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    shorter = min(a["end"] - a["start"], b["end"] - b["start"])
    return inter / shorter if shorter > 0 else 0.0


def rank_candidates(cands: list[dict], segments: list[dict], cfg: dict, k: int) -> list[dict]:
    """One comparative pass: the LLM picks the top k candidates, best first.

    Small models are unreliable at scoring a long list consistently, but good at
    choosing and ordering the best few. Returns the chosen candidates in order.
    """
    if len(cands) <= 1:
        return cands[:k]
    items = []
    for i, c in enumerate(cands):
        text = " ".join(segments[j]["text"] for j in range(c["first_line"], c["last_line"] + 1))
        if len(text) > 500:
            text = text[:500] + "..."
        items.append(f"[id {i}] ({c['end'] - c['start']:.0f}s) {c['title']}\n{text}")

    k = min(k, len(cands))
    llm_cfg = dict(cfg["llm"], think=cfg["clipper"].get("rank_with_thinking", True))
    t0 = time.time()
    reply = chat_json(llm_cfg, [
        {"role": "user", "content": RANK_PROMPT.format(n=len(cands), k=k, items="\n\n".join(items))},
    ], RANK_SCHEMA)

    order = []
    for i in reply.get("best_ids", []):
        if isinstance(i, int) and 0 <= i < len(cands) and i not in order:
            order.append(i)
    from_ai = len(order[:k])
    # If the model returned fewer than k, fill up with the best remaining first-pass picks.
    for i in sorted(range(len(cands)), key=lambda i: cands[i]["score"], reverse=True):
        if len(order) >= k:
            break
        if i not in order:
            order.append(i)
    print(f"  AI chose {from_ai}/{k} clips ({time.time() - t0:.0f}s)")
    return [cands[i] for i in order[:k]]


def pick_moments(transcript_path: Path, cfg: dict, max_clips: int | None = None) -> Path:
    transcript_path = Path(transcript_path)
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    segments = data["segments"]
    duration = data.get("duration") or (segments[-1]["end"] if segments else 0)
    ccfg = cfg["clipper"]
    min_s, max_s = float(ccfg["min_seconds"]), float(ccfg["max_seconds"])
    max_clips = max_clips or int(ccfg["max_clips"])

    style = ccfg.get("style_notes") or ""
    system = SYSTEM_PROMPT.format(
        min_s=int(min_s), max_s=int(max_s),
        style=f"\nAbout this content: {style}" if style else "",
    )

    chunks = make_chunks(segments, ccfg["chunk_minutes"] * 60, ccfg["chunk_overlap_seconds"])
    print(f"Reading {len(segments)} transcript lines ({fmt_time(duration)}) in {len(chunks)} chunks "
          f"with {cfg['llm']['model']}...")

    candidates = []
    started = time.time()
    for n, (a, b) in enumerate(chunks, 1):
        lines = "\n".join(
            f"#{i} [{fmt_time(segments[i]['start'])}] {segments[i]['text']}" for i in range(a, b + 1)
        )
        t0 = time.time()
        reply = chat_json(cfg["llm"], [
            {"role": "system", "content": system},
            {"role": "user", "content": USER_PROMPT.format(lines=lines, min_s=int(min_s), max_s=int(max_s))},
        ], SCHEMA)

        kept = 0
        for c in reply.get("clips", []):
            s, e = c.get("start_line"), c.get("end_line")
            if not isinstance(s, int) or not isinstance(e, int):
                continue
            s, e = max(a, min(s, e)), min(b, max(s, e))  # stay inside this chunk
            fitted = fit_length(segments, s, e, min_s, max_s)
            if not fitted:
                continue
            s, e = fitted
            candidates.append({
                "start": round(max(0.0, segments[s]["start"] - PAD_BEFORE), 2),
                "end": round(min(duration, segments[e]["end"] + PAD_AFTER), 2),
                "score": max(1, min(10, int(c.get("score", 0)))),
                "title": c.get("title", "").strip(),
                "hook": c.get("hook", "").strip(),
                "reason": c.get("reason", "").strip(),
                "first_line": s,
                "last_line": e,
            })
            kept += 1
        print(f"  chunk {n}/{len(chunks)} [{fmt_time(segments[a]['start'])}-{fmt_time(segments[b]['end'])}]: "
              f"{kept} candidate(s) ({time.time() - t0:.0f}s)")

    # Remove duplicates: best first, drop anything overlapping a better pick.
    candidates.sort(key=lambda c: c["score"], reverse=True)
    unique = []
    for c in candidates:
        if not any(overlap_ratio(c, k) > DUPLICATE_OVERLAP for k in unique):
            unique.append(c)
    unique = [c for c in unique if c["score"] >= ccfg["min_score"]]
    print(f"\n{len(candidates)} candidates, {len(unique)} after removing duplicates and low scores. "
          f"Ranking them together...")

    chosen = rank_candidates(unique, segments, cfg, max_clips)

    clips = []
    for rank, c in enumerate(chosen, 1):
        text = " ".join(segments[i]["text"] for i in range(c["first_line"], c["last_line"] + 1))
        clips.append({
            "rank": rank,
            "start": c["start"],
            "end": c["end"],
            "duration": round(c["end"] - c["start"], 2),
            "first_pass_score": c["score"],  # per-chunk score; `rank` is the real order
            "title": c["title"],
            "hook": c["hook"],
            "reason": c["reason"],
            "text": text,
        })

    out_path = transcript_path.parent / "clips.json"
    out_path.write_text(json.dumps({
        "source": data.get("source"),
        "transcript": str(transcript_path.resolve()),
        "model": cfg["llm"]["model"],
        "created": datetime.now().isoformat(timespec="seconds"),
        "settings": {k: ccfg[k] for k in ("min_seconds", "max_seconds", "max_clips", "min_score")},
        "candidates_considered": len(candidates),
        "clips": clips,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Kept {len(clips)} clips (took {time.time() - started:.0f}s total)\n")
    for c in clips:
        print(f"#{c['rank']:<2} {fmt_time(c['start'])}-{fmt_time(c['end'])} "
              f"({c['duration']:.0f}s)  {c['title']}")
        print(f"     hook: {c['hook'][:90]}")
        print(f"     why:  {c['reason'][:90]}")
    print(f"\nSaved {out_path}")
    return out_path

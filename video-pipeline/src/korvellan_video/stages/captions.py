"""Stage: build word-by-word captions for a clip as an .ass subtitle file.

Style: a few words at a time, uppercase, bold with a thick outline, and the word
being spoken highlighted. ffmpeg burns the .ass file into the video during render.

.ass (Advanced SubStation Alpha) is used because it supports per-word colors,
outlines, and exact positioning, and ffmpeg renders it natively (libass).
"""
from pathlib import Path

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,{outline},3,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

STRIP_PUNCT = ",.;:"   # removed from the end of words (looks cleaner)
END_PUNCT = ".?!"      # a word ending in one of these closes the caption group


def hex_to_ass(color: str) -> str:
    """'#FFE600' (RGB) -> '&H0000E6FF&' (ASS uses BGR)."""
    c = color.lstrip("#")
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H00{b}{g}{r}&".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def clean_word(word: str) -> str:
    w = word.strip().replace("{", "(").replace("}", ")").replace("\\", "/")
    return w.rstrip(STRIP_PUNCT).upper() or w.upper()


def clip_words(segments: list[dict], start: float, end: float) -> list[dict]:
    """All words inside [start, end], with times relative to the clip start."""
    words = []
    for seg in segments:
        if seg["end"] < start or seg["start"] > end:
            continue
        for w in seg.get("words", []):
            if w["start"] >= start - 0.05 and w["end"] <= end + 0.05 and w["word"].strip():
                words.append({"start": w["start"] - start, "end": w["end"] - start, "word": w["word"].strip()})
    return words


def group_words(words: list[dict], max_words: int, max_chars: int, max_gap: float) -> list[list[dict]]:
    groups, cur = [], []
    for w in words:
        if cur:
            too_many = len(cur) >= max_words
            too_long = sum(len(x["word"]) + 1 for x in cur) + len(w["word"]) > max_chars
            paused = w["start"] - cur[-1]["end"] > max_gap
            if too_many or too_long or paused:
                groups.append(cur)
                cur = []
        cur.append(w)
        if w["word"].rstrip('"\'').endswith(tuple(END_PUNCT)):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def margin_for(ccfg: dict, layout: str) -> int:
    """Caption distance from the bottom edge; can be set per layout in config."""
    m = ccfg.get("margin_bottom", 470)
    if isinstance(m, dict):
        return int(m.get(layout, m.get("blur", 470)))
    return int(m)


def build_ass(segments: list[dict], clip_start: float, clip_end: float, out_path: Path,
              ccfg: dict, width: int = 1080, height: int = 1920, layout: str = "blur") -> int:
    """Write the .ass file for one clip. Returns the number of caption groups."""
    duration = clip_end - clip_start
    words = clip_words(segments, clip_start, clip_end)
    groups = group_words(words, int(ccfg.get("max_words", 3)), int(ccfg.get("max_chars", 18)), 0.6)
    highlight = hex_to_ass(ccfg.get("highlight_color", "#FFE600"))

    lines = [HEADER.format(
        w=width, h=height, font=ccfg.get("font", "Arial Black"), size=int(ccfg.get("font_size", 84)),
        outline=int(ccfg.get("outline", 7)), margin_v=margin_for(ccfg, layout),
    )]
    for gi, group in enumerate(groups):
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else duration
        # Keep the caption up until the next one if the gap is short (avoids flicker).
        group_end = next_start if next_start - group[-1]["end"] < 0.5 else group[-1]["end"] + 0.2
        group_end = min(group_end, duration)
        texts = [clean_word(w["word"]) for w in group]
        for wi, w in enumerate(group):
            start = w["start"]
            end = group[wi + 1]["start"] if wi + 1 < len(group) else group_end
            if end <= start:
                continue
            parts = [f"{{\\c{highlight}}}{t}{{\\r}}" if j == wi else t for j, t in enumerate(texts)]
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{' '.join(parts)}")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(groups)

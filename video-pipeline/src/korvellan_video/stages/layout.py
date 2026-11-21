"""Stage: decide how to turn a wide video into a vertical one (once per video).

The `auto` layout samples frames across the video and looks for faces (YuNet face
detector, runs on the CPU in a few seconds):

- one small face that stays in the same spot  -> a streamer's face cam -> "split"
  (face cam on top, gameplay below)
- one large face                               -> talking head -> "crop" centered on the face
- no consistent face, or several people        -> "blur" (full frame on a blurred background)
  ("several people" = 1.5+ faces per frame on average, which also catches group
  shows where camera cuts move people around between shots)

A manual face cam box in config.yaml (render.facecam) overrides detection.
The decision is saved to <output>/<video>/layout.json so you can see why.
"""
import json
from pathlib import Path

import numpy as np

from ..config import PROJECT_DIR
from ..media import grab_frame, probe_video

MODEL = PROJECT_DIR / "models" / "face_detection_yunet_2023mar.onnx"

SAMPLES = 15            # frames checked per video
DETECT_W = 960          # frames are shrunk to this width for detection (fast)
MIN_FACE_H = 0.07       # ignore faces smaller than 7% of frame height (game HUD portraits etc.)
PRESENT = 0.6           # a face must be in >= 60% of sampled frames to count
GROUP_AVG = 1.5         # >= this many faces per frame on average = several people -> blur
FACECAM_MAX_H = 0.22    # a persistent face smaller than this is a face cam overlay
EDGE = 0.35             # ...and face cams sit toward the sides (center x outside the middle 30%)

OUT_W, OUT_H = 1080, 1920
SPLIT_TOP_H = 640       # face cam panel height in "split" (top third)


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


def _cluster_faces(frames: list[list[tuple]], fw: int, fh: int) -> list[dict]:
    """Group face boxes from different frames that are in the same place."""
    clusters = []
    for i, boxes in enumerate(frames):
        for b in boxes:
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            for c in clusters:
                if abs(cx - c["cx"]) < 0.06 * fw and abs(cy - c["cy"]) < 0.10 * fh:
                    c["boxes"].append(b)
                    c["frames"].add(i)
                    break
            else:
                clusters.append({"cx": cx, "cy": cy, "boxes": [b], "frames": {i}})
    return clusters


def _split_plan(face_box: tuple, w: int, h: int) -> dict:
    """Face cam crop (top panel) around the face, and a gameplay crop that avoids it."""
    fx, fy, fwid, fhei = face_box
    # Top panel: a 1080:640 box around the face, the face's center a bit above middle.
    rh = min(h, fhei * 1.8)
    rw = min(w, rh * OUT_W / SPLIT_TOP_H)
    rh = rw * SPLIT_TOP_H / OUT_W
    cx, cy = fx + fwid / 2, fy + fhei / 2
    x = min(max(0, cx - rw / 2), w - rw)
    y = min(max(0, cy - 0.45 * rh), h - rh)
    cam = [_even(x), _even(y), _even(rw), _even(rh)]
    cam[0] = min(cam[0], w - cam[2])
    cam[1] = min(cam[1], h - cam[3])

    # Bottom panel: full-height gameplay slice, shifted away from the face cam if they overlap.
    gw = _even(h * OUT_W / (OUT_H - SPLIT_TOP_H))
    gw = min(gw, w - w % 2)
    gx = (w - gw) / 2
    cam_left, cam_right = cam[0], cam[0] + cam[2]
    if cam_left < gx + gw and cam_right > gx:  # overlap
        gx = cam_right if cx < w / 2 else cam_left - gw
    gx = _even(min(max(0, gx), w - gw))
    return {"facecam": cam, "gameplay_x": gx, "gameplay_w": gw}


def plan_layout(source: Path, cfg: dict, requested: str) -> dict:
    """Return a layout plan: {"layout": ..., "reason": ..., plus crop parameters}."""
    w, h, duration = probe_video(source)
    plan = {"source_size": [w, h]}
    manual = cfg.get("render", {}).get("facecam")

    if requested == "blur":
        return {**plan, "layout": "blur", "reason": "blur requested"}
    if manual and requested in ("auto", "split"):
        x, y, cw, ch = (int(v) for v in manual)
        p = _split_plan((x, y, cw, ch), w, h)
        p["facecam"] = [_even(x), _even(y), _even(cw), _even(ch)]  # use the box exactly
        return {**plan, **p, "layout": "split", "reason": "face cam box set manually in config.yaml"}

    import cv2  # imported here so other commands don't need OpenCV loaded
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # hide harmless backend warning

    dh = _even(DETECT_W * h / w)
    detector = cv2.FaceDetectorYN.create(str(MODEL), "", (DETECT_W, dh), 0.7)
    frames = []
    for i in range(SAMPLES):
        t = duration * (0.03 + 0.94 * i / (SAMPLES - 1))
        img = grab_frame(source, t, DETECT_W, dh)
        if img is None:
            continue
        _, faces = detector.detect(img)
        boxes = []
        for f in faces if faces is not None else []:
            box = tuple(float(v) for v in f[:4])
            if box[3] / dh >= MIN_FACE_H:
                boxes.append(box)
        frames.append(boxes)

    n = len(frames)
    clusters = _cluster_faces(frames, DETECT_W, dh)
    persistent = sorted((c for c in clusters if n and len(c["frames"]) >= PRESENT * n),
                        key=lambda c: len(c["frames"]), reverse=True)
    avg_faces = sum(len(b) for b in frames) / n if n else 0.0
    plan["detection"] = {
        "frames_checked": n,
        "avg_faces_per_frame": round(avg_faces, 2),
        "persistent_faces": [
            {"seen_in": f"{len(c['frames'])}/{n}",
             "center_x": round(c["cx"] / DETECT_W, 2), "center_y": round(c["cy"] / dh, 2),
             "height": round(float(np.median([b[3] for b in c["boxes"]])) / dh, 3)}
            for c in persistent
        ],
    }

    scale = w / DETECT_W
    group = avg_faces >= GROUP_AVG  # several people on screen (camera cuts can hide this from clustering)
    if len(persistent) == 1 and not group:
        c = persistent[0]
        box = tuple(float(v) * scale for v in np.median(np.array(c["boxes"]), axis=0))
        face_h = box[3] / h
        face_cx = (box[0] + box[2] / 2) / w
        is_facecam = face_h < FACECAM_MAX_H and (face_cx < EDGE or face_cx > 1 - EDGE)

        if is_facecam and requested in ("auto", "split"):
            return {**plan, **_split_plan(box, w, h), "layout": "split",
                    "reason": f"face cam found ({face_h:.0%} of frame height, toward the "
                              f"{'left' if face_cx < 0.5 else 'right'}) in {len(c['frames'])}/{n} frames"}
        if requested in ("auto", "crop"):
            cw = _even(h * 9 / 16)
            x = _even(min(max(0, box[0] + box[2] / 2 - cw / 2), w - cw))
            return {**plan, "layout": "crop", "crop_x": x, "crop_w": cw,
                    "reason": f"one main person on camera ({face_h:.0%} of frame height); "
                              f"cropping centered on their face"}

    if requested == "split":
        reason = "split requested but no face cam found; using blur instead"
    elif requested == "crop":
        return {**plan, "layout": "crop", "crop_x": _even((w - h * 9 / 16) / 2), "crop_w": _even(h * 9 / 16),
                "reason": "crop requested; no single face found, cropping the center"}
    elif group or len(persistent) > 1:
        reason = f"several people on camera (~{avg_faces:.1f} faces per frame); blur keeps everyone in frame"
    else:
        reason = "no consistent face found (gameplay/screen content)"
    return {**plan, "layout": "blur", "reason": reason}


def save_plan(plan: dict, path: Path) -> None:
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

"""Find and follow the streamer's face in the webcam overlay, for the face-on-top / gameplay-below layout.

Returns a crop box that follows the face smoothly over the clip, or None when there is no stable face
(no webcam, or OpenCV not installed) so the renderer falls back to the full-frame layout.
"""
from pathlib import Path

from .common import ROOT, log

YUNET = ROOT / "models" / "face_detection_yunet_2023mar.onnx"

PANEL_ASPECT = 1080 / 768  # width / height of the top panel


def track_face(path, dur, samples=18):
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not W or not H:
        return None
    yunet = None
    if YUNET.exists() and hasattr(cv2, "FaceDetectorYN"):
        try:  # OpenCV's own DNN face model: far fewer false matches than the classic cascade
            yunet = cv2.FaceDetectorYN.create(str(YUNET), "", (960, int(H * 960.0 / W)), 0.8, 0.3, 50)
        except Exception as e:
            log(f"  YuNet unavailable ({str(e)[:80]}), using cascade")
    det = None
    if yunet is None:
        try:
            det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        except Exception:
            det = None
        if det is None or det.empty():
            log("  face finder unavailable (OpenCV face data missing) -> full-frame layout")
            cap.release()
            return None
    scale = 960.0 / W
    hits = []  # (t, cx, cy, size) in source pixels
    for i in range(samples):
        t = dur * (i + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        small = cv2.resize(frame, (960, int(H * scale)))
        if yunet is not None:
            _, found = yunet.detect(small)
            faces = [] if found is None else [tuple(int(v) for v in f[:4]) for f in found]
        else:
            gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(16, 16))
        for (x, y, w, h) in faces:
            hits.append((t, (x + w / 2) / scale, (y + h / 2) / scale, w / scale))
    cap.release()
    if not hits:
        return None
    # the webcam face stays in roughly one place: take the biggest cluster of detections
    best = []
    for _, cx, cy, s in hits:
        group = [h for h in hits if abs(h[1] - cx) < s * 0.6 and abs(h[2] - cy) < s * 0.6]
        if len(group) > len(best):
            best = group
    times = sorted({h[0] for h in best})
    if len(times) < max(4, samples // 3):
        log(f"  no stable webcam face ({len(times)}/{samples} frames)")
        return None
    best.sort(key=lambda h: h[0])
    size = sorted(h[3] for h in best)[len(best) // 2]
    xs, ys = [h[1] for h in best], [h[2] for h in best]
    if (max(xs) - min(xs)) > size * 0.9 or (max(ys) - min(ys)) > size * 0.9:
        log("  face candidate moves too much (likely in-game), using full-frame layout")
        return None
    ch = min(H, size * 2.4)          # head and shoulders
    cw = min(W, ch * PANEL_ASPECT)
    ch = cw / PANEL_ASPECT
    # one point per sampled time, lightly smoothed so the crop glides instead of jittering
    pts = []
    for t in times:
        g = [h for h in best if h[0] == t]
        pts.append((t, sum(h[1] for h in g) / len(g), sum(h[2] for h in g) / len(g)))
    sm = []
    for i, (t, x, y) in enumerate(pts):
        win = pts[max(0, i - 1): i + 2]
        sm.append((t, sum(p[1] for p in win) / len(win), sum(p[2] for p in win) / len(win)))
    track = []
    for t, x, y in sm:
        x0 = min(max(0, x - cw / 2), W - cw)
        y0 = min(max(0, y - ch * 0.42), H - ch)
        track.append((round(t, 2), int(x0), int(y0)))
    log(f"  webcam face found in {len(times)}/{samples} frames, crop {int(cw)}x{int(ch)}")
    return {"w": int(cw) // 2 * 2, "h": int(ch) // 2 * 2, "track": track, "W": W, "H": H}


def lerp_expr(track, idx):
    """ffmpeg expression (in t) that linearly interpolates track[*][idx] over time."""
    if len(track) == 1:
        return str(track[0][idx])
    expr = str(track[-1][idx])
    for i in range(len(track) - 2, -1, -1):
        t0, t1 = track[i][0], track[i + 1][0]
        v0, v1 = track[i][idx], track[i + 1][idx]
        seg = f"({v0}+({v1}-{v0})*(t-{t0})/{max(0.01, t1 - t0):.2f})"
        expr = f"if(lt(t\\,{t1})\\,{seg}\\,{expr})"
    first = track[0]
    return f"if(lt(t\\,{first[0]})\\,{first[idx]}\\,{expr})"

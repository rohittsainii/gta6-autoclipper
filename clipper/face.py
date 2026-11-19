"""Find and follow the streamer's face in the webcam overlay, for the face-on-top / gameplay-below layout.

Returns a crop box that follows the face smoothly over the clip, or None when there is no stable face
(no webcam, or OpenCV not installed) so the renderer falls back to the full-frame layout.
"""
from .common import log

PANEL_ASPECT = 1080 / 768  # width / height of the top panel


def track_face(path, dur, samples=14):
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not W or not H:
        return None
    try:
        det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    except Exception:
        det = None
    if det is None or det.empty():
        log("  face finder unavailable (OpenCV face data missing) -> full-frame layout")
        cap.release()
        return None
    scale = 640.0 / W
    hits = []  # (t, cx, cy, size) in source pixels
    for i in range(samples):
        t = dur * (i + 0.5) / samples
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        small = cv2.resize(frame, (640, int(H * scale)))
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(22, 22))
        for (x, y, w, h) in faces:
            hits.append((t, (x + w / 2) / scale, (y + h / 2) / scale, w / scale))
    cap.release()
    if not hits:
        return None
    # the webcam face stays in roughly one place: take the biggest cluster of detections
    best = []
    for _, cx, cy, s in hits:
        group = [h for h in hits if abs(h[1] - cx) < s * 1.2 and abs(h[2] - cy) < s * 1.2]
        if len(group) > len(best):
            best = group
    times = sorted({h[0] for h in best})
    if len(times) < max(4, samples // 3):
        log(f"  no stable webcam face ({len(times)}/{samples} frames)")
        return None
    best.sort(key=lambda h: h[0])
    size = sorted(h[3] for h in best)[len(best) // 2]
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

"""Render the clips Claude picked (picks/*.json) into ready-to-post 9:16 videos + POST.md.

picks file format:
{
  "candidate_file": "candidates/<file>.json",
  "clips": [
    {"moment_id": "m3", "start": 1234.5, "end": 1271.0,
     "hook": "SHORT HOOK, NO EMOJI", "caption": "post caption with #tags",
     "words": [optional list of {"w","s","e"} replacing the transcript, e.g. Hinglish romanised]}
  ]
}
"""
import json
import re
import sys
import time
from pathlib import Path

from .common import CONFIG, PICKS, ROOT, WORK, load_json, log, run, save_json, write_runlog, ytdlp_base

W, H = 1080, 1920
OUT = ROOT / "out"
FONTS = ROOT / "fonts"


def ass_time(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def clean(text):
    text = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    return "".join(ch for ch in text if ord(ch) < 0x10000)  # libass can't draw colour emoji


def build_ass(words, dur, hook, disclosure, caption_y, hook_y):
    font = "Anton" if (FONTS / "Anton-Regular.ttf").exists() else "DejaVu Sans"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1
Style: Hook,{font},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0000000,-1,0,0,0,100,100,1,0,3,18,0,5,70,70,0,1
Style: Tag,DejaVu Sans,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,10,0,9,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if hook:
        ev.append(f"Dialogue: 2,{ass_time(0)},{ass_time(dur)},Hook,,0,0,0,,{{\\pos({W//2},{hook_y})}}{clean(hook).upper()}")
    if disclosure:
        ev.append(f"Dialogue: 3,{ass_time(0)},{ass_time(min(4, dur))},Tag,,0,0,0,,{clean(disclosure)}")
    # word-by-word captions: groups of up to 3 words, the spoken word turns yellow
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.!?,]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.4
        for wi, w in enumerate(g):
            s = w["s"]
            e = g[wi + 1]["s"] if wi + 1 < len(g) else max(g_end, w["e"])
            if e - s > 2.5:
                e = s + 2.5
            parts = []
            for k, x in enumerate(g):
                t = clean(x["w"]).upper()
                parts.append("{\\c&H00F0FF&\\fscx108\\fscy108}" + t + "{\\c&HFFFFFF&\\fscx100\\fscy100}" if k == wi else t)
            ev.append(f"Dialogue: 1,{ass_time(s)},{ass_time(e)},Cap,,0,0,0,,{{\\pos({W//2},{caption_y})}}" + " ".join(parts))
    return head + "\n".join(ev) + "\n"


def download_section(url, s, e, dest):
    for f in WORK.glob(dest.name + ".*"):
        f.unlink()
    if url.startswith("file://") or Path(url).exists():  # local recording / tests
        out = f"{dest}.mp4"
        run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{s:.2f}", "-i", url.replace("file://", ""),
             "-t", f"{e - s:.2f}", "-c", "copy", out])
        return out
    cmd = ytdlp_base() + ["-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--download-sections", f"*{s:.2f}-{e:.2f}",
                          "--merge-output-format", "mp4", "-o", f"{dest}.%(ext)s", "--print", "after_move:filepath", url]
    out = run(cmd, timeout=1800).strip().splitlines()
    return out[-1]


def render_clip(src, ass_path, facecam, out_path, dur):
    fontsdir = f":fontsdir={FONTS}" if FONTS.exists() else ""
    if facecam:  # facecam on top (40%), gameplay below (60%)
        fx, fy, fw, fh = facecam
        cam_h, game_h = 768, H - 768
        vf = (f"[0:v]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,"
              f"crop={W}:{cam_h}[cam];"
              f"[0:v]crop=ih*{W}/{game_h}:ih,scale={W}:{game_h}[game];"
              f"[cam][game]vstack,ass={ass_path}{fontsdir}[v]")
    else:  # full frame in the middle, blurred copy as background
        vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.18[bg];"
              f"[0:v]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2-60,ass={ass_path}{fontsdir}[v]")
    run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", src, "-t", f"{dur:.2f}",
         "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out_path)], timeout=1800)


def main(pick_files):
    cfg = {c["id"]: c for c in load_json(CONFIG, {})["campaigns"]}
    OUT.mkdir(exist_ok=True)
    made, post = [], ["# Clips ready to post\n"]
    for pf in pick_files:
        pf = Path(pf)
        picks = load_json(pf, {})
        if picks.get("status") == "rendered":
            continue
        cand = load_json(ROOT / picks["candidate_file"], {})
        camp = cfg.get(cand.get("campaign"), {})
        moments = {m["id"]: m for m in cand.get("moments", [])}
        for n, c in enumerate(picks.get("clips", []), 1):
            name = f"{cand['campaign']}_{pf.stem}_{n}"
            try:
                s, e = float(c["start"]), float(c["end"])
                dur = e - s
                words = c.get("words") or [w for w in moments.get(c.get("moment_id"), {}).get("words", [])
                                           if s - 0.1 <= w["s"] < e]
                words = [{"w": w["w"], "s": w["s"] - s, "e": w["e"] - s} for w in words]
                facecam = camp.get("facecam")
                cap_y = 1640 if facecam else 1500
                hook_y = 120 if facecam else 380
                ass = WORK / f"{name}.ass"
                ass.write_text(build_ass(words, dur, c.get("hook", ""), camp.get("on_video_disclosure", ""),
                                         cap_y, hook_y))
                log(f"{name}: downloading {s:.0f}-{e:.0f}s")
                src = download_section(cand["vod_url"], s, e, WORK / f"src_{name}")
                outp = OUT / f"{name}.mp4"
                render_clip(src, ass, facecam, outp, dur)
                Path(src).unlink(missing_ok=True)
                made.append(outp)
                post.append(f"## {outp.name}  ({camp.get('name', cand['campaign'])})\n\n"
                            f"Hook: {c.get('hook', '')}\n\n```\n{c.get('caption', '')}\n```\n"
                            f"Source: {cand['vod_url']} at {int(s//3600)}:{int(s%3600//60):02d}:{int(s%60):02d}\n")
                log(f"{name}: done ({outp.stat().st_size/1e6:.1f} MB)")
            except Exception as ex:
                log(f"{name}: ERROR {str(ex)[:400]}")
        picks["status"] = "rendered"
        picks["rendered_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        save_json(pf, picks)
    (OUT / "POST.md").write_text("\n".join(post))
    log(f"rendered {len(made)} clip(s)")
    write_runlog("Renderer")
    return made


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(str(p) for p in PICKS.glob("*.json"))
    main(files)

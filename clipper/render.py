"""Render the clips Claude picked (picks/*.json) into ready-to-post 9:16 videos.

Each clip:  [voice intro over the clip, stream audio ducked] -> clip -> [voice outro over a held last frame]
with word-by-word captions, a hook title and an on-screen credit to the creator.
Every finished clip is written to out/<name>/ (clip.mp4 + meta.json) and published as its own GitHub Release
by .github/workflows/render.yml; Zapier posts each new (non-pre-)release to YouTube, Instagram and Facebook.

picks file format:
{
  "candidate_file": "candidates/<file>.json",
  "sample": false,                      # true = pre-release, never auto-posted
  "clips": [
    {"moment_id": "m3", "start": 1234.5, "end": 1271.0,
     "hook": "SHORT HOOK, NO EMOJI",
     "title": "YouTube title (max 90 chars)",
     "caption": "post text with hashtags",
     "voice_intro": "max ~14 words, said over the start",
     "voice_outro": "max ~22 words, Claude's own take",
     "words": [optional transcript override, e.g. Hinglish romanised]}
  ]
}
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from .common import CONFIG, PICKS, ROOT, WORK, load_json, log, run, save_json, write_runlog, ytdlp_base

W, H = 1080, 1920
OUT = ROOT / "out"
FONTS = ROOT / "fonts"
SFX = ROOT / "assets" / "sfx"
YELLOW, CYAN = "&H00F0FF&", "&HFFE52E&"   # ASS colours are BGR


def ass_time(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


SWEARS = re.compile(r"^((mother)?f+u+c+k\w*|sh+i+t+(s|ty|ting|ted)?|bitch\w*|n+i+g+(g+a|a|e+r)s?|cunts?|dick(head)?s?|puss(y|ies)|fag+(ot)?s?)$", re.I)


def _is_swear(word):
    core = re.sub(r"[^A-Za-z]", "", word)
    return bool(core) and bool(SWEARS.match(core))


def mask(word):
    """F*CK-style caption masking for strong swears."""
    if not _is_swear(word):
        return word
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 2) + m.group(0)[-1]
                  if len(m.group(0)) > 2 else m.group(0), word, count=1)


def bleep_ranges(words):
    return [(max(0.0, w["s"] - 0.03), w["e"] + 0.03) for w in words if _is_swear(w["w"])]


def clean(text):
    text = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    return "".join(ch for ch in text if ord(ch) < 0x10000)  # libass can't draw colour emoji


def caption_events(words, y, hi_colour, style="Cap"):
    """Word-by-word captions: groups of up to 3 words, the spoken word is highlighted."""
    groups, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) == 3 or re.search(r"[.!?,]$", w["w"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    ev = []
    for gi, g in enumerate(groups):
        g_end = groups[gi + 1][0]["s"] if gi + 1 < len(groups) else g[-1]["e"] + 0.4
        for wi, w in enumerate(g):
            s = w["s"]
            e = g[wi + 1]["s"] if wi + 1 < len(g) else max(g_end, w["e"])
            e = min(e, s + 2.5)
            parts = []
            for k, x in enumerate(g):
                t = clean(mask(x["w"])).upper()
                parts.append("{\\c" + hi_colour + "\\fscx108\\fscy108}" + t + "{\\c&HFFFFFF&\\fscx100\\fscy100}"
                             if k == wi else t)
            pop = "{\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)}" if wi == 0 else ""
            ev.append(f"Dialogue: 1,{ass_time(s)},{ass_time(e)},{style},,0,0,0,,{{\\pos({W//2},{y})}}" + pop + " ".join(parts))
    return ev


def build_ass(stream_words, intro_words, outro_words, clip_dur, total, hook, credit, disclosure, cap_y, hook_y,
              flashes=()):
    font = "Anton" if (FONTS / "Anton-Regular.ttf").exists() else "DejaVu Sans"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1
Style: Narr,{font},84,&H00FFFFFF,&H00FFFFFF,&H00401A2E,&H64000000,-1,0,0,0,100,100,1,0,1,7,3,5,60,60,0,1
Style: Hook,{font},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&HC0000000,-1,0,0,0,100,100,1,0,3,18,0,5,70,70,0,1
Style: Tag,DejaVu Sans,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,10,0,9,40,40,40,1
Style: Credit,DejaVu Sans,36,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,10,0,2,40,40,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    if hook:
        ev.append(f"Dialogue: 2,{ass_time(0)},{ass_time(clip_dur)},Hook,,0,0,0,,{{\\pos({W//2},{hook_y})}}{clean(hook).upper()}")
    if credit:
        ev.append(f"Dialogue: 3,{ass_time(0)},{ass_time(total)},Credit,,0,0,0,,CLIP: {clean(credit)}")
    if disclosure:
        ev.append(f"Dialogue: 3,{ass_time(0)},{ass_time(min(4, total))},Tag,,0,0,0,,{clean(disclosure)}")
    for t in flashes:  # quick white flash on the big moment
        ev.append(f"Dialogue: 5,{ass_time(t)},{ass_time(t + 0.22)},Hook,,0,0,0,,"
                  "{\\an7\\pos(0,0)\\bord0\\shad0\\1c&HFFFFFF&\\alpha&H50&\\fad(0,180)\\p1}"
                  f"m 0 0 l {W} 0 {W} {H} 0 {H}{{\\p0}}")
    ev += caption_events(intro_words, cap_y, CYAN, "Narr")
    ev += caption_events(stream_words, cap_y, YELLOW)
    ev += caption_events(outro_words, cap_y, CYAN, "Narr")
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
    path = run(cmd, timeout=1800).strip().splitlines()[-1]
    if not has_video(path):  # Twitch sometimes hands back audio only near the live edge: retry forcing a video format
        log("  downloaded section had no video, retrying with a video-only format choice")
        Path(path).unlink(missing_ok=True)
        cmd[cmd.index("-f") + 1] = "b[vcodec!=none][height<=1080]/b[vcodec!=none]"
        path = run(cmd, timeout=1800).strip().splitlines()[-1]
        if not has_video(path):
            raise RuntimeError("source section has no video stream")
    return path


def has_video(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index",
                          "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return bool(out)


def render_clip(src, ass_path, facecam, out_path, clip_dur, intro_mp3, outro_mp3, intro_dur, outro_at, total,
                face=None, sfx=(), bleeps=()):
    fontsdir = f":fontsdir={FONTS}" if FONTS.exists() else ""
    hold = max(0.0, total - clip_dur)
    if face:  # streamer's face (tracked) on top 40%, gameplay below 60%
        from .face import lerp_expr
        cam_h, game_h = 768, H - 768
        xe, ye = lerp_expr(face["track"], 1), lerp_expr(face["track"], 2)
        v = (f"[0:v]trim=0:{clip_dur:.3f},setpts=PTS-STARTPTS,split[s1][s2];"
             f"[s1]crop={face['w']}:{face['h']}:{xe}:{ye},scale={W}:{cam_h}[cam];"
             f"[s2]crop=ih*{W}/{game_h}:ih,scale={W}:{game_h}[game];[cam][game]vstack[lay];")
    elif facecam:  # fixed facecam box from config on top (40%), gameplay below (60%)
        fx, fy, fw, fh = facecam
        cam_h, game_h = 768, H - 768
        v = (f"[0:v]trim=0:{clip_dur:.3f},setpts=PTS-STARTPTS,split[s1][s2];"
             f"[s1]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h}[cam];"
             f"[s2]crop=ih*{W}/{game_h}:ih,scale={W}:{game_h}[game];[cam][game]vstack[lay];")
    else:  # full frame in the middle, blurred copy as background
        v = (f"[0:v]trim=0:{clip_dur:.3f},setpts=PTS-STARTPTS,split[s1][s2];"
             f"[s1]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2,eq=brightness=-0.18[bg];"
             f"[s2]scale={W}:-2[fg];[bg][fg]overlay=0:(H-h)/2-60[lay];")
    v += f"[lay]fps=30,tpad=stop_mode=clone:stop_duration={hold:.3f},ass={ass_path}{fontsdir}[v]"
    inputs = ["-i", src]
    duck_until = intro_dur + 0.2 if intro_mp3 else 0
    a = (f"[0:a]atrim=0:{clip_dur:.3f},asetpts=PTS-STARTPTS,"
         f"volume='if(lt(t,{duck_until:.2f}),0.22,1)':eval=frame")
    if bleeps:  # mute the swear in the stream audio and lay a beep over it
        on = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in bleeps)
        a += f",volume='if({on},0,1)':eval=frame"
    a += ",apad[a0]"
    mix = ["[a0]"]
    if intro_mp3:
        inputs += ["-i", intro_mp3]
        a += f";[{inputs.count('-i') - 1}:a]aresample=48000,adelay=150|150,volume=1.6[ai]"
        mix.append("[ai]")
    if outro_mp3:
        inputs += ["-i", outro_mp3]
        d = int(outro_at * 1000)
        a += f";[{inputs.count('-i') - 1}:a]aresample=48000,adelay={d}|{d},volume=1.6[ao]"
        mix.append("[ao]")
    if bleeps:
        on = "+".join(f"between(t,{a0:.2f},{b0:.2f})" for a0, b0 in bleeps)
        inputs += ["-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration={clip_dur:.2f}"]
        a += f";[{inputs.count('-i') - 1}:a]volume='if({on},0.18,0)':eval=frame[bp]"
        mix.append("[bp]")
    for k, (t, name, vol) in enumerate(sfx):
        inputs += ["-i", name]
        d = max(0, int(t * 1000))
        a += f";[{inputs.count('-i') - 1}:a]aresample=48000,adelay={d}|{d},volume={vol}[x{k}]"
        mix.append(f"[x{k}]")
    a += f";{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", *inputs, "-filter_complex", v + ";" + a,
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(out_path)], timeout=1800)


def media_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def main(pick_files):
    cfg = load_json(CONFIG, {})
    creators = {c["id"]: c for c in cfg.get("creators", cfg.get("campaigns", []))}
    channels = cfg.get("channels", {})
    OUT.mkdir(exist_ok=True)
    made = []
    for pf in pick_files:
        pf = Path(pf)
        picks = load_json(pf, {})
        if picks.get("status") == "rendered":
            continue
        cand = load_json(ROOT / picks["candidate_file"], {})
        cr = creators.get(cand.get("campaign"), {})
        ch = channels.get(cr.get("channel", "en"), {})
        sample = bool(picks.get("sample"))
        if cr.get("added_by") == "scout":  # campaigns only: never use auto-found creators
            cr = dict(cr, permission=False)
        if not sample and not cr.get("permission"):
            log(f"{pf.name}: SKIPPED, no clipping permission recorded for {cr.get('name', cand.get('campaign'))}")
            picks["status"] = "rendered"
            picks["skipped"] = "no permission"
            save_json(pf, picks)
            continue
        moments = {m["id"]: m for m in cand.get("moments", [])}
        for n, c in enumerate(picks.get("clips", []), 1):
            name = f"{cand['campaign']}_{pf.stem}_{n}"
            try:
                s, e = float(c["start"]), float(c["end"])
                clip_dur = e - s
                # commentary voice
                intro_mp3 = outro_mp3 = None
                intro_words, outro_words, intro_dur, outro_dur = [], [], 0.0, 0.0
                if c.get("voice_intro"):
                    from .voice import speak
                    intro_mp3 = str(WORK / f"{name}_intro.mp3")
                    intro_words, intro_dur = speak(c["voice_intro"], ch.get("voice_id"), intro_mp3, ch.get("voice_speed", 1.08))
                    intro_words = [{"w": w["w"], "s": w["s"] + 0.15, "e": w["e"] + 0.15} for w in intro_words]
                if c.get("voice_outro"):
                    from .voice import speak
                    outro_mp3 = str(WORK / f"{name}_outro.mp3")
                    outro_words, outro_dur = speak(c["voice_outro"], ch.get("voice_id"), outro_mp3, ch.get("voice_speed", 1.08))
                outro_at = clip_dur + 0.25
                total = outro_at + outro_dur + 0.6 if outro_mp3 else clip_dur
                outro_words = [{"w": w["w"], "s": w["s"] + outro_at, "e": w["e"] + outro_at} for w in outro_words]
                # stream captions (skip what is said under the voice intro)
                words = c.get("words") or [w for w in moments.get(c.get("moment_id"), {}).get("words", [])
                                           if s - 0.1 <= w["s"] < e]
                words = [{"w": w["w"], "s": w["s"] - s, "e": w["e"] - s} for w in words]
                words = [w for w in words if w["s"] >= intro_dur + 0.25]
                log(f"{name}: downloading {s:.0f}-{e:.0f}s")
                src = download_section(cand["vod_url"], s, e, WORK / f"src_{name}")
                facecam = cr.get("facecam")
                face = None
                if facecam != "off" and not facecam:
                    try:
                        from .face import track_face
                        face = track_face(src, clip_dur)
                    except Exception as fe:
                        log(f"  face tracking failed ({str(fe)[:120]}) -> full-frame layout")
                        face = None
                split = bool(face or facecam)
                cap_y = 1560 if split else 1500
                hook_y = 840 if split else 380
                # sound effects: whoosh in, picker's cues (boom/scratch/ding/gasp/pop), riser into the outro
                cues = [(0.0, "whoosh", 0.55)]
                flashes = []
                for q in c.get("sfx", []):
                    t = float(q.get("t", 0)) - s
                    kind = q.get("type", "boom")
                    if 0 <= t <= clip_dur:
                        cues.append((t, kind, 0.8 if kind == "boom" else 0.6))
                        if kind == "boom":
                            flashes.append(t)
                if outro_mp3:
                    cues.append((max(0.0, outro_at - 1.8), "riser", 0.35))
                sfx = [(t, str(SFX / f"{k}.mp3"), v) for t, k, v in cues if (SFX / f"{k}.mp3").exists()]
                ass = WORK / f"{name}.ass"
                ass.write_text(build_ass(words, intro_words, outro_words, clip_dur, total, c.get("hook", ""),
                                         cr.get("credit", ""), cr.get("on_video_disclosure", ""), cap_y, hook_y,
                                         flashes))
                folder = OUT / name
                folder.mkdir(parents=True, exist_ok=True)
                outp = folder / "clip.mp4"
                render_clip(src, ass, None if facecam == "off" else facecam, outp, clip_dur, intro_mp3, outro_mp3,
                            intro_dur, outro_at, total, face=face, sfx=sfx, bleeps=bleep_ranges(words))
                Path(src).unlink(missing_ok=True)
                credit_line = f"🎥 Clip from {cr.get('credit', cand.get('streamer', ''))}"
                hashtags = ch.get("hashtags", "#GTA6 #shorts")
                title = (c.get("title") or c.get("hook", "GTA 6 moment")).strip()[:90]
                caption = c.get("caption", "").strip()
                description = f"{caption}\n\n{credit_line}\n{hashtags}".strip()
                save_json(folder / "meta.json", {
                    "title": title, "description": description, "sample": sample,
                    "creator": cr.get("name", cand.get("streamer", "")), "channel": cr.get("channel", "en"),
                    "source": f"{cand['vod_url']} at {int(s//3600)}:{int(s%3600//60):02d}:{int(s%60):02d}",
                    "duration": round(media_duration(str(outp)), 1)})
                made.append(folder)
                log(f"{name}: done ({outp.stat().st_size/1e6:.1f} MB, {media_duration(str(outp)):.1f}s)")
            except Exception as ex:
                log(f"{name}: ERROR {str(ex)[:400]}")
        picks["status"] = "rendered"
        picks["rendered_at"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        save_json(pf, picks)
    log(f"rendered {len(made)} clip(s)")
    write_runlog("Renderer", "render_log.md")
    return made


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(str(p) for p in PICKS.glob("*.json"))
    main(files)

"""Find the best moments in new stream footage and write candidates/*.json for Claude to pick from.

Signals (combined into one score per second of stream):
  1. Twitch clips viewers made (strongest signal: the audience already chose the moment)
  2. YouTube "most replayed" heatmap (YouTube VODs)
  3. Loudness spikes vs. the streamer's own recent baseline (screaming, laughing, hype)
Only the top windows are transcribed, so speech-to-text cost stays small.
"""
import math
import os
import statistics
import time
from pathlib import Path

from .common import (CANDIDATES, CONFIG, STATE, WORK, load_json, log, run, save_json,
                     write_runlog, ytdlp_base, ytdlp_json)
from .transcribe import transcribe

WINDOW_BEFORE, WINDOW_AFTER = 70, 40   # seconds around a peak sent to Claude
MIN_GAP = 150                           # seconds between two picked peaks


# ---------- listing new footage ----------

def list_vods(src, max_n):
    if src["platform"] == "twitch":
        h = src["handle"]
        flat = ytdlp_json(f"https://www.twitch.tv/{h}/videos?filter=archives&sort=time", flat=True)
        urls = [e.get("url") or f"https://www.twitch.tv/videos/{e['id'].lstrip('v')}" for e in flat.get("entries", [])][:max_n]
    else:
        url = src["url"]
        if "watch?v=" in url or "youtu.be/" in url:
            urls = [url]
        else:
            flat = ytdlp_json(url, flat=True)
            urls = []
            for e in flat.get("entries", []):
                if e.get("live_status") in ("is_live", "is_upcoming"):
                    continue  # YouTube: wait until the stream has ended
                urls.append(e.get("url") or f"https://www.youtube.com/watch?v={e['id']}")
                if len(urls) >= max_n:
                    break
    vods = []
    for u in urls:
        try:
            info = ytdlp_json(u)
        except Exception as e:
            log(f"  could not read {u}: {str(e)[:200]}")
            continue
        vods.append({
            "url": info.get("webpage_url") or u,
            "id": f"{src['platform']}_{info['id']}",
            "title": info.get("title", ""),
            "start_ts": info.get("timestamp") or info.get("release_timestamp"),
            "duration": float(info.get("duration") or 0),
            "live": bool(info.get("is_live")) or info.get("live_status") == "is_live",
            "heatmap": info.get("heatmap") or [],
        })
    return vods


def twitch_viewer_clips(handle, cache):
    """Viewer-made clips from the last 7 days: [{ts, views, title, url}]."""
    flat = ytdlp_json(f"https://www.twitch.tv/{handle}/clips?filter=clips&range=7d", flat=True)
    out = []
    for e in (flat.get("entries") or [])[:40]:
        cid = e.get("id") or e.get("url")
        if cid not in cache:
            try:
                i = ytdlp_json(e.get("url") or f"https://clips.twitch.tv/{cid}")
                cache[cid] = {"ts": i.get("timestamp"), "views": i.get("view_count") or 0,
                              "title": i.get("title", ""), "url": i.get("webpage_url")}
            except Exception as ex:
                log(f"  clip {cid} unreadable: {str(ex)[:120]}")
                continue
        out.append(cache[cid])
    return out


# ---------- audio + loudness ----------

def download_audio(vod_url, a, b, dest):
    for f in Path(dest).parent.glob(Path(dest).name + ".*"):
        f.unlink()
    cmd = ytdlp_base() + ["-f", "ba/Audio_Only/audio_only/worst", "--download-sections", f"*{a:.0f}-{b:.0f}",
                          "-o", f"{dest}.%(ext)s", "--print", "after_move:filepath", vod_url]
    out = run(cmd, timeout=3 * 3600).strip().splitlines()
    return out[-1] if out else str(next(Path(dest).parent.glob(Path(dest).name + ".*")))


def loudness_per_second(path):
    rms_file = WORK / "rms.txt"
    af = ("aresample=8000,aformat=channel_layouts=mono,asetnsamples=n=8000:p=0,"
          f"astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file={rms_file}")
    run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", path, "-vn", "-af", af, "-f", "null", "-"],
        timeout=3600)
    vals = []
    for line in rms_file.read_text().splitlines():
        if "RMS_level=" in line:
            v = line.split("=", 1)[1]
            vals.append(-90.0 if v in ("-inf", "inf", "nan") else max(-90.0, float(v)))
    return vals


def excitement(levels):
    """dB above the local baseline (median of the surrounding ~5 minutes)."""
    n = len(levels)
    out = [0.0] * n
    step = 15  # recompute the baseline every 15 s for speed
    base = 0.0
    for i in range(n):
        if i % step == 0:
            lo, hi = max(0, i - 150), min(n, i + 150)
            base = statistics.median(levels[lo:hi])
        lo, hi = max(0, i - 2), min(n, i + 3)
        out[i] = max(0.0, sum(levels[lo:hi]) / (hi - lo) - base)
    return out


# ---------- scoring ----------

def score_chunk(n, a, excite, clips, vod_start, heatmap):
    score = [e / 6.0 for e in excite]            # ~6 dB above normal = 1 point
    why = [set() for _ in range(n)]
    for i, e in enumerate(excite):
        if e >= 6:
            why[i].add("loud")
    if vod_start:
        for c in clips:
            if not c.get("ts"):
                continue
            off = c["ts"] - vod_start - a          # clip is created ~at the end of the moment
            if -5 <= off < n + 5:
                w = 3 + math.log10(c["views"] + 1)
                for i in range(max(0, int(off) - 30), min(n, int(off) + 3)):
                    score[i] += w
                    why[i].add(f"viewer clip ({c['views']} views): {c['title'][:60]}")
    for h in heatmap:
        s0, s1, v = h.get("start_time", 0) - a, h.get("end_time", 0) - a, h.get("value", 0)
        for i in range(max(0, int(s0)), min(n, int(s1) + 1)):
            score[i] += 4 * v
            if v > 0.6:
                why[i].add("most replayed")
    return score, why


def pick_peaks(score, k, threshold=0.8):
    order = sorted(range(len(score)), key=lambda i: score[i], reverse=True)
    peaks = []
    for i in order:
        if score[i] < threshold or len(peaks) >= k:
            break
        if all(abs(i - p) >= MIN_GAP for p in peaks):
            peaks.append(i)
    return sorted(peaks)


# ---------- main ----------

def process_chunk(camp, vod, a, b, clips, settings):
    tag = f"{vod['id']}_{int(a)}"
    log(f"  chunk {a/3600:.2f}h-{b/3600:.2f}h of '{vod['title'][:60]}'")
    audio = download_audio(vod["url"], a, b, str(WORK / f"chunk_{tag}"))
    levels = loudness_per_second(audio)
    n = len(levels)
    if n < 60:
        log("  audio too short, skipping")
        return 0
    score, why = score_chunk(n, a, excitement(levels), clips, vod["start_ts"], vod["heatmap"])
    peaks = pick_peaks(score, settings["moments_per_chunk"])
    log(f"  {len(peaks)} candidate moments")
    moments = []
    for j, p in enumerate(peaks):
        s, e = max(0, p - WINDOW_BEFORE), min(n, p + WINDOW_AFTER)
        win = WORK / f"win_{tag}_{j}.mp3"
        run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", str(s), "-t", str(e - s), "-i", audio,
             "-ac", "1", "-ar", "16000", "-b:a", "64k", str(win)])
        words, engine = transcribe(str(win), camp["language"])
        for w in words:  # make times absolute (seconds into the VOD)
            w["s"] = round(w["s"] + a + s, 2)
            w["e"] = round(w["e"] + a + s, 2)
        moments.append({
            "id": f"m{j+1}",
            "start": round(a + s, 1), "end": round(a + e, 1), "peak": round(a + p, 1),
            "score": round(score[p], 2),
            "signals": sorted({x for i in range(max(0, p - 30), min(n, p + 5)) for x in why[i]})[:6],
            "stt": engine,
            "text": " ".join(w["w"] for w in words),
            "words": words,
        })
        win.unlink(missing_ok=True)
    Path(audio).unlink(missing_ok=True)
    if moments:
        save_json(CANDIDATES / f"{tag}.json", {
            "status": "new", "campaign": camp["id"], "streamer": camp["streamer"], "language": camp["language"],
            "vod_url": vod["url"], "vod_title": vod["title"], "chunk": [a, b],
            "created": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "moments": moments})
    return len(moments)


def main():
    cfg = load_json(CONFIG, {})
    st = load_json(STATE, {"vods": {}, "clip_cache": {}})
    st.setdefault("vods", {}), st.setdefault("clip_cache", {})
    settings = cfg["settings"]
    chunk = settings["chunk_hours"] * 3600
    total = 0
    deadline = time.time() + float(os.environ.get("MAX_RUN_MINUTES", "240")) * 60
    for camp in cfg["campaigns"]:
        if not camp.get("enabled"):
            continue
        for src in camp.get("sources", []):
            log(f"{camp['id']}: checking {src}")
            try:
                vods = list_vods(src, settings["max_vods_per_source"])
                clips = twitch_viewer_clips(src["handle"], st["clip_cache"]) if src["platform"] == "twitch" else []
                log(f"  {len(vods)} recent VOD(s), {len(clips)} viewer clips")
            except Exception as e:
                log(f"  ERROR listing: {str(e)[:300]}")
                continue
            for vod in vods:
                ended = (vod["start_ts"] or 0) + vod["duration"]
                if not vod["live"] and vod["start_ts"] and time.time() - ended > settings.get("max_age_hours", 24) * 3600:
                    log(f"  skipping old stream: {vod['title'][:60]}")
                    continue
                v = st["vods"].setdefault(vod["id"], {
                    "done_until": max(0.0, vod["duration"] - settings["backfill_hours"] * 3600),
                    "title": vod["title"], "campaign": camp["id"]})
                while time.time() < deadline:
                    a = v["done_until"]
                    left = vod["duration"] - a
                    if left <= 30 or (vod["live"] and left < settings["min_new_minutes"] * 60):
                        break
                    b = min(vod["duration"], a + chunk)
                    try:
                        total += process_chunk(camp, vod, a, b, clips, settings)
                    except Exception as e:
                        log(f"  ERROR on chunk: {str(e)[:400]}")
                        break
                    v["done_until"] = b
                    save_json(STATE, st)
    # keep the clip cache small
    if len(st["clip_cache"]) > 600:
        st["clip_cache"] = dict(list(st["clip_cache"].items())[-400:])
    save_json(STATE, st)
    log(f"done: {total} new candidate moments")
    write_runlog("Moment finder")


if __name__ == "__main__":
    main()

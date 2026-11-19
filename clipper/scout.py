"""Permission scout: find GTA 6 creators who say in their YouTube description that anyone may clip them.

Adds them to config/campaigns.json with the exact quote as proof. Their videos are then only used when that
video's own description contains the permission (permission_mode = "per_video"), checked again by the finder.
Twitch descriptions/panels are not readable without an API key, so Twitch creators are added by hand.
"""
import re
import time

from .common import CONFIG, ROOT, load_json, log, save_json, ytdlp_json

QUERIES = ["GTA 6 live", "GTA 6 stream", "GTA 6 gameplay", "GTA 6 funny moments", "GTA 6 hindi live"]
PER_QUERY = 15
LOG = ROOT / "state" / "scout_log.json"

ALLOW = re.compile(
    r"(feel free to (clip|use (my|these|this|the) (clips?|content|stream|video|footage))"
    r"|you (can|may|are (free|welcome) to) clip"
    r"|(clipping|clips?) (is |are )?(allowed|welcome|permitted|encouraged)"
    r"|free to clip|anyone (can|may) clip|go ahead and clip"
    r"|clip (my|this|these|the) (streams?|videos?|content).{0,40}(credit|tag|link)"
    r"|(reupload|re-upload|repost)s? (are |is )?(allowed|fine|welcome).{0,40}(credit|tag|link))",
    re.I)
DENY = re.compile(r"(don'?t|do not|no|not allowed to|never) (clip|re-?upload|repost|steal|use my)|without permission|"
                  r"all rights reserved.{0,40}(clip|re-?upload)|copyright strike|ask (me )?(first|for|before)|with (my )?permission only|members?[- ]only|only (for|on) (my|the official)", re.I)


def permission_quote(description):
    """Exact permission sentence from a description, or None (also None if a refusal is present)."""
    if not description:
        return None
    if DENY.search(description):
        return None
    m = ALLOW.search(description)
    if not m:
        return None
    a = max(description.rfind("\n", 0, m.start()) + 1, m.start() - 120)
    b = description.find("\n", m.end())
    b = m.end() + 120 if b == -1 else min(b, m.end() + 120)
    return description[a:b].strip()


def language_of(info):
    lang = (info.get("language") or "").lower()
    if lang.startswith("hi"):
        return "hi"
    text = (info.get("title", "") + " " + (info.get("description") or "")[:300])
    if re.search(r"[ऀ-ॿ]", text) or re.search(r"\b(hindi|bhai|desi)\b", text, re.I):
        return "hi"
    return "en"


def run_scout(every_hours=6):
    st = load_json(LOG, {"last_run": 0, "seen": {}})
    if time.time() - st.get("last_run", 0) < every_hours * 3600:
        return 0
    cfg = load_json(CONFIG, {})
    creators = cfg.setdefault("creators", [])
    known = {c["id"] for c in creators}
    added = 0
    for q in QUERIES:
        try:
            res = ytdlp_json(f"ytsearchdate{PER_QUERY}:{q}", flat=True)
        except Exception as e:
            log(f"scout: search '{q}' failed: {str(e)[:150]}")
            continue
        for e in res.get("entries") or []:
            vid = e.get("id")
            if not vid or vid in st["seen"]:
                continue
            st["seen"][vid] = int(time.time())
            try:
                info = ytdlp_json(f"https://www.youtube.com/watch?v={vid}")
            except Exception:
                continue
            quote = permission_quote(info.get("description") or "")
            if not quote:
                continue
            cid = "yt_" + (info.get("channel_id") or info.get("uploader_id") or vid)
            if cid in known:
                continue
            lang = language_of(info)
            handle = info.get("uploader_url") or info.get("channel_url") or ""
            creators.append({
                "id": cid,
                "name": info.get("channel") or info.get("uploader") or cid,
                "enabled": lang == "en",  # Hindi creators wait until the Indian channel exists
                "permission": True,
                "permission_mode": "per_video",
                "permission_proof": f"\"{quote}\" (found in {info.get('webpage_url')} on {time.strftime('%Y-%m-%d')})",
                "channel": lang,
                "language": lang,
                "credit": f"{info.get('channel') or info.get('uploader')} ({handle.replace('https://www.', '')})",
                "sources": [{"platform": "youtube", "url": (info.get("channel_url") or handle).rstrip("/") + "/streams"},
                            {"platform": "youtube", "url": (info.get("channel_url") or handle).rstrip("/") + "/videos"}],
                "facecam": None,
                "added_by": "scout",
            })
            known.add(cid)
            added += 1
            log(f"scout: + {info.get('channel')} ({lang}) — \"{quote[:90]}\"")
    # keep the seen-list small
    if len(st["seen"]) > 3000:
        st["seen"] = dict(sorted(st["seen"].items(), key=lambda kv: kv[1])[-2000:])
    st["last_run"] = int(time.time())
    save_json(LOG, st)
    if added:
        save_json(CONFIG, cfg)
    log(f"scout: {added} new creator(s) with written clip permission")
    return added

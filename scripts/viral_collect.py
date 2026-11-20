"""Collect public YouTube Shorts data for GTA 6 streamer clips (no downloads of video).

Step 1: search recent Shorts for each query, keep ones <= 3 min.
Step 2: for the channels that show up most, list their last 40 Shorts (views) for a median.
Step 3: for the top videos, fetch full metadata (description, tags, upload date, likes, comments).
"""
import json, subprocess, sys, collections

COOKIES, OUT = sys.argv[1], sys.argv[2]
QUERIES = [
    "lacy gta 6", "kai cenat gta 6", "kreekcraft gta 6", "brettliftsxp gta 6", "dylan page gta 6",
    "dasgasd3m gta 6", "gta 6 funny moments shorts", "gta 6 streamer reaction", "ishowspeed gta 6",
    "gta 6 clips", "gta 6 first time playing", "gta 6 npc funny",
]


def ytdlp(args, timeout=300):
    r = subprocess.run(["yt-dlp", "--cookies", COOKIES, "--no-warnings", "--ignore-errors", *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout


def flat(url, n):
    out = ytdlp(["--flat-playlist", "--playlist-end", str(n), "-J", url])
    try:
        return json.loads(out).get("entries") or []
    except Exception:
        return []


videos = {}
for q in QUERIES:
    # sp=EgIIAw%3D%3D = uploaded this week
    url = "https://www.youtube.com/results?search_query=" + q.replace(" ", "+") + "&sp=EgIIAw%253D%253D"
    for e in flat(url, 60):
        d = e.get("duration") or 0
        if not e.get("id") or not d or d > 180:
            continue
        videos[e["id"]] = {"id": e["id"], "title": e.get("title"), "views": e.get("view_count"),
                           "duration": d, "channel": e.get("channel") or e.get("uploader"),
                           "channel_id": e.get("channel_id"), "query": q}
    print(q, len(videos), flush=True)

# channel medians: channels with the most hits
counts = collections.Counter(v["channel_id"] for v in videos.values() if v.get("channel_id"))
channels = {}
for cid, _ in counts.most_common(30):
    ents = flat(f"https://www.youtube.com/channel/{cid}/shorts", 40)
    views = sorted(x.get("view_count") or 0 for x in ents if x.get("view_count") is not None)
    if len(views) >= 4:
        channels[cid] = {"n": len(views), "median": views[len(views) // 2],
                         "name": next((v["channel"] for v in videos.values() if v["channel_id"] == cid), cid)}
    print("channel", cid, len(views), flush=True)

# full metadata for the 60 most-viewed
top = sorted(videos.values(), key=lambda v: v.get("views") or 0, reverse=True)[:60]
for v in top:
    out = ytdlp(["--skip-download", "-J", f"https://www.youtube.com/shorts/{v['id']}"], timeout=120)
    try:
        j = json.loads(out)
    except Exception:
        continue
    v.update({"description": (j.get("description") or "")[:600], "tags": (j.get("tags") or [])[:25],
              "upload_date": j.get("upload_date"), "likes": j.get("like_count"),
              "comments": j.get("comment_count"), "followers": j.get("channel_follower_count"),
              "width": j.get("width"), "height": j.get("height")})

json.dump({"videos": list(videos.values()), "channels": channels}, open(OUT, "w"), indent=1, ensure_ascii=False)
print("done", len(videos), len(channels))

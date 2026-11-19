"""One-time: generate the channel's own sound-effect library with ElevenLabs Sound Effects.
Only missing files are generated, so re-running costs nothing."""
import os
import sys
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "assets" / "sfx"
LIBRARY = {
    "whoosh": ("fast clean cinematic whoosh transition, short swipe, no music", 1.0),
    "boom": ("deep punchy bass boom impact hit, comedic meme style, short, no music", 1.5),
    "scratch": ("vinyl record scratch stop, comedic fail moment, short", 1.0),
    "riser": ("short tension riser swell building up, ends abruptly, no music", 2.0),
    "ding": ("bright cartoon notification ding, single clean hit", 0.8),
    "pop": ("soft quick bubble pop click, ui sound", 0.5),
    "gasp": ("small audience shocked gasp ooh, short crowd reaction", 1.5),
}


def main():
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("ELEVENLABS_API_KEY missing")
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (prompt, secs) in LIBRARY.items():
        f = OUT / f"{name}.mp3"
        if f.exists() and f.stat().st_size > 1000:
            print(f"{name}: already have it")
            continue
        r = requests.post("https://api.elevenlabs.io/v1/sound-generation",
                          headers={"xi-api-key": key},
                          json={"text": prompt, "duration_seconds": secs, "prompt_influence": 0.6}, timeout=120)
        if r.status_code != 200:
            print(f"{name}: ERROR {r.status_code} {r.text[:200]}")
            continue
        f.write_bytes(r.content)
        print(f"{name}: saved {len(r.content)} bytes")


if __name__ == "__main__":
    main()

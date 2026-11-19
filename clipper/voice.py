"""Commentary voice: ElevenLabs text-to-speech with word timings (for captions)."""
import base64
import os
import time

from .common import log

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps"
MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")


def speak(text, voice_id, out_mp3, speed=1.08):
    """Write narration to out_mp3. Returns (words, duration) with words = [{"w","s","e"}] in seconds."""
    import requests

    key = os.environ["ELEVENLABS_API_KEY"]
    body = {"text": text, "model_id": MODEL,
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "speed": speed}}
    for attempt in range(3):
        r = requests.post(TTS_URL.format(voice=voice_id), params={"output_format": "mp3_44100_128"},
                          headers={"xi-api-key": key}, json=body, timeout=120)
        if r.status_code == 200:
            break
        if r.status_code in (401, 402, 403):
            raise PermissionError(f"ElevenLabs TTS refused ({r.status_code}): {r.text[:200]}")
        log(f"TTS error {r.status_code}: {r.text[:150]}")
        time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError("ElevenLabs TTS failed 3 times")
    j = r.json()
    with open(out_mp3, "wb") as fh:
        fh.write(base64.b64decode(j["audio_base64"]))
    al = j.get("alignment") or j.get("normalized_alignment") or {}
    chars = al.get("characters", [])
    starts = al.get("character_start_times_seconds", [])
    ends = al.get("character_end_times_seconds", [])
    words, cur, s0, e0 = [], "", None, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"w": cur, "s": s0, "e": e0})
            cur, s0 = "", None
            continue
        if s0 is None:
            s0 = s
        cur += ch
        e0 = e
    if cur:
        words.append({"w": cur, "s": s0, "e": e0})
    dur = ends[-1] if ends else 0.0
    return words, dur

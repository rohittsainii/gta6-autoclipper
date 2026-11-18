"""Speech to text with word timestamps.

Primary: ElevenLabs Scribe API (secret ELEVENLABS_API_KEY). Fallback: faster-whisper on CPU.
Returns a list of {"w": word, "s": start_sec, "e": end_sec} relative to the audio file.
"""
import os
import time

from .common import log

EL_URL = "https://api.elevenlabs.io/v1/speech-to-text"
EL_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v2")
EL_LANG = {"en": "eng", "hi": "hin"}

_whisper = None


def _elevenlabs(path, lang):
    import requests  # installed with yt-dlp[default]

    key = os.environ["ELEVENLABS_API_KEY"]
    data = {"model_id": EL_MODEL, "timestamps_granularity": "word", "tag_audio_events": "true"}
    if lang in EL_LANG and lang != "hi":  # let Scribe auto-detect Hindi/Hinglish mixes
        data["language_code"] = EL_LANG[lang]
    for attempt in range(3):
        with open(path, "rb") as fh:
            r = requests.post(EL_URL, headers={"xi-api-key": key}, data=data,
                              files={"file": (os.path.basename(path), fh, "audio/mpeg")}, timeout=300)
        if r.status_code == 200:
            out = []
            for w in r.json().get("words", []):
                if w.get("type") == "word" and w.get("text", "").strip():
                    out.append({"w": w["text"].strip(), "s": round(w["start"], 2), "e": round(w["end"], 2)})
            return out
        if r.status_code in (401, 402, 403):
            raise PermissionError(f"ElevenLabs refused ({r.status_code}): {r.text[:200]}")
        log(f"ElevenLabs error {r.status_code}, retrying: {r.text[:150]}")
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("ElevenLabs failed 3 times")


def _faster_whisper(path, lang):
    global _whisper
    if _whisper is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:  # only installed when actually needed (no ElevenLabs key / out of credits)
            import subprocess, sys
            log("installing faster-whisper 1.2.1")
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "faster-whisper==1.2.1"], check=True)
            from faster_whisper import WhisperModel
        size = os.environ.get("WHISPER_MODEL", "small")
        log(f"loading faster-whisper '{size}' (CPU)")
        _whisper = WhisperModel(size, device="cpu", compute_type="int8")
    segs, _ = _whisper.transcribe(path, language=None if lang == "hi" else lang,
                                   word_timestamps=True, vad_filter=True)
    out = []
    for seg in segs:
        for w in seg.words or []:
            if w.word.strip():
                out.append({"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)})
    return out


_el_disabled = False


def transcribe(path, lang="en"):
    global _el_disabled
    if os.environ.get("ELEVENLABS_API_KEY") and not _el_disabled:
        try:
            return _elevenlabs(path, lang), "elevenlabs"
        except PermissionError as e:  # out of credits / bad key -> fall back for the rest of the run
            log(f"{e} -> switching to faster-whisper")
            _el_disabled = True
        except Exception as e:
            log(f"ElevenLabs failed ({e}) -> faster-whisper for this window")
    return _faster_whisper(path, lang), "faster-whisper"

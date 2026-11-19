"""Shared helpers: paths, JSON state, running commands, run log."""
import datetime as dt
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "campaigns.json"
STATE = ROOT / "state" / "state.json"
CANDIDATES = ROOT / "candidates"
PICKS = ROOT / "picks"
WORK = Path(os.environ.get("CLIPPER_WORK", "/tmp/clipper"))
WORK.mkdir(parents=True, exist_ok=True)

_log_lines = []


def log(msg):
    stamp = dt.datetime.utcnow().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    _log_lines.append(line)


def write_runlog(title, name):
    path = ROOT / "state" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    path.write_text(f"# {title}\n\nRun at {now}\n\n```\n" + "\n".join(_log_lines[-300:]) + "\n```\n")


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def run(cmd, check=True, capture=True, timeout=None):
    """Run a command (list), return stdout text."""
    res = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    if check and res.returncode != 0:
        tail = (res.stderr or "")[-1500:]
        raise RuntimeError(f"command failed ({res.returncode}): {' '.join(map(str, cmd[:6]))} ...\n{tail}")
    return res.stdout if capture else ""


def ytdlp_base():
    """yt-dlp with optional YouTube cookies (secret YT_COOKIES written to a file)."""
    base = ["yt-dlp", "--no-warnings", "--retries", "5", "--socket-timeout", "30"]
    cookies = os.environ.get("YT_COOKIES", "").strip()
    if cookies:
        cf = WORK / "cookies.txt"
        cf.write_text(cookies + "\n")
        base += ["--cookies", str(cf)]
    return base


def ytdlp_json(url, flat=False, extra=None):
    cmd = ytdlp_base() + ["-J", "--skip-download"]
    if flat:
        cmd.append("--flat-playlist")
    cmd += (extra or []) + [url]
    return json.loads(run(cmd, timeout=600))

"""Text to speech with an engine already on the computer (macOS `say`). Nothing is uploaded."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

MAX_CHARS = 1500


class TtsError(Exception):
    pass


def available() -> bool:
    return shutil.which("say") is not None and shutil.which("ffmpeg") is not None


@lru_cache(maxsize=1)
def voices() -> list[dict]:
    """[{name, lang, sample}] from `say -v ?`, quirky voices (novelty effects) left out."""
    if not shutil.which("say"):
        return []
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=15).stdout
    res = []
    for line in out.splitlines():
        m = re.match(r"^(.+?)\s{2,}([a-z]{2}[_-][A-Za-z]{2,4})\s+#\s*(.*)$", line)
        if not m:
            continue
        name, lang, sample = m.group(1).strip(), m.group(2), m.group(3)
        res.append({"name": name, "lang": lang.replace("_", "-"), "sample": sample})
    novelty = {"Albert", "Bad News", "Bahh", "Bells", "Boing", "Bubbles", "Cellos", "Good News", "Jester", "Organ",
               "Superstar", "Trinoids", "Whisper", "Wobble", "Zarvox"}
    return [v for v in res if v["name"] not in novelty] or res


def status() -> dict:
    if not available():
        return {"ok": False, "engine": "none", "voices": [],
                "hint": "Text to speech needs the macOS `say` command and FFmpeg. It is not available on this computer."}
    vs = voices()
    return {"ok": bool(vs), "engine": "macOS system voices", "voices": vs,
            "hint": None if vs else "No system voices are installed (System Settings > Accessibility > Spoken Content)."}


def synthesize(text: str, voice: str, rate: float, out: Path) -> Path:
    """Write a 44.1 kHz stereo WAV. `rate` is a speed multiplier (1 = normal)."""
    text = (text or "").strip()
    if not text:
        raise TtsError("Type some text first.")
    if len(text) > MAX_CHARS:
        raise TtsError(f"Keep the text under {MAX_CHARS} characters.")
    if not available():
        raise TtsError("No speech engine is available on this computer.")
    if voice not in {v["name"] for v in voices()}:
        raise TtsError(f"Unknown voice '{voice}'.")
    wpm = int(max(80, min(400, 175 * rate)))
    with tempfile.TemporaryDirectory(prefix="ave_tts_") as tmp:
        aiff = Path(tmp) / "speech.aiff"
        # text goes through a file so a leading "-" or shell-looking text is never read as an option
        txt = Path(tmp) / "in.txt"
        txt.write_text(text, encoding="utf-8")
        r = subprocess.run(["say", "-v", voice, "-r", str(wpm), "-o", str(aiff), "-f", str(txt)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not aiff.exists():
            raise TtsError(f"The speech engine failed: {(r.stderr or '').strip()[:200] or 'unknown error'}")
        f = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", "44100", "-ac", "2", str(out)],
                           capture_output=True, text=True, timeout=120)
        if f.returncode != 0:
            raise TtsError(f"Could not convert the speech: {f.stderr.strip()[:200]}")
    return out

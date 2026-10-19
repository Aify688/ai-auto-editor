"""Voice and sound effects for a clip's audio (the frontend lists the same ids in lib/audioEffects.ts)."""
from __future__ import annotations

EFFECTS: dict[str, list[str]] = {
    "denoise": ["highpass=f=70", "afftdn=nr=20:nf=-35:tn=1"],
    "voice": ["highpass=f=90", "equalizer=f=250:t=q:w=1:g=-2", "equalizer=f=3200:t=q:w=1:g=3",
              "acompressor=threshold=-20dB:ratio=3:attack=15:release=250", "alimiter=limit=0.95"],
    "deep": ["asetrate=44100*0.8", "aresample=44100", "atempo=1.25"],
    "chipmunk": ["asetrate=44100*1.35", "aresample=44100", "atempo=0.74"],
    "robot": ["afftfilt=real='hypot(re,im)':imag='0':win_size=512:overlap=0.75"],
    "echo": ["aecho=0.8:0.88:420|760:0.35|0.22"],
    "radio": ["highpass=f=500", "lowpass=f=3200", "acompressor=threshold=-18dB:ratio=4", "volume=1.4"],
}


def filters(effect: str | None) -> list[str]:
    return list(EFFECTS.get(effect or "", []))


def valid(effect: str | None) -> str | None:
    return effect if effect in EFFECTS else None

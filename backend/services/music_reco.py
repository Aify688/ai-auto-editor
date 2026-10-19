"""Pick background music that suits the footage, from the bundled CC BY library only.

Signals come from the analysis the editor already caches (motion, scene-cut pace, speech/audio activity) plus the
chosen editing style and any mood the user asked for in words. Scoring is a transparent heuristic: it compares the
"energy" of the footage with the energy of each track (its mood bucket and measured tempo, see
backend/assets/music/CREDITS.md) and explains the match in plain words. No copyrighted commercial songs are used.
"""
from __future__ import annotations

import math

from . import music_library

# Tempo measured per track (CREDITS.md) and the energy each mood bucket stands for (0 = calm, 1 = intense).
TEMPO = {"lib:cinematic": 117.5, "lib:energetic": 143.6, "lib:relaxing": 80.7, "lib:happy": 117.5, "lib:dramatic": 129.2}
MOOD_ENERGY = {"relaxing": 0.15, "cinematic": 0.45, "happy": 0.65, "dramatic": 0.75, "energetic": 0.95}
MOOD_WORDS = {"relaxing": "calm", "cinematic": "cinematic", "happy": "cheerful", "dramatic": "dramatic", "energetic": "upbeat"}


def footage_profile(rows: list[dict], data: dict) -> dict:
    """energy 0-1 (movement + cutting pace), speech 0-1 (share of the audio that is active), faces 0-1."""
    motion, scenes_total, seconds, active, faces, with_audio = [], 0, 0.0, [], [], 0
    for m in rows:
        d = data.get(m["id"])
        if not d or m["kind"] != "video":
            continue
        motion += [v for v in d["visual"].get("motion", []) if v is not None]
        sc = d.get("scenes") or []
        scenes_total += len(sc)
        seconds += float(m["duration"] or 0)
        fs = d["visual"].get("faces", [])
        if fs:
            faces.append(sum(1 for f in fs if f) / len(fs))
        if m["has_audio"]:
            dur = float(m["duration"] or 0) or 1.0
            silent = sum(min(b, dur) - a for a, b in d["audio"].get("silences", []))
            active.append(max(0.0, 1 - silent / dur))
            with_audio += 1
    mean_motion = sum(motion) / len(motion) if motion else 0.0
    motion_level = min(1.0, mean_motion / 0.12)
    pace = min(1.0, (scenes_total / max(seconds, 1.0)) * 60 / 20) if seconds else 0.0
    return {"energy": round(0.6 * motion_level + 0.4 * pace, 3), "motion": round(motion_level, 3), "pace": round(pace, 3),
            "speech": round(sum(active) / len(active), 3) if active else 0.0,
            "faces": round(sum(faces) / len(faces), 3) if faces else 0.0, "videos": len(rows)}


STYLE_ENERGY = {"energetic": 0.8, "dynamic": 0.8, "marketing": 0.8, "social": 0.75, "travel": 0.55, "vlog": 0.5, "cinematic": 0.45,
                "documentary": 0.35, "professional": 0.35, "minimal": 0.3}


def style_profile(rows: list[dict], style: str) -> dict:
    """Fallback when the footage has not been analysed yet: what the files and the chosen style alone say."""
    videos = [m for m in rows if m["kind"] == "video"]
    talking = any(m["has_audio"] for m in videos)
    return {"energy": STYLE_ENERGY.get(style, 0.5), "motion": 0.0, "pace": 0.0, "speech": 0.5 if talking else 0.0, "faces": 0.0,
            "videos": len(rows)}


def recommend(profile: dict, style: str, mood_hint: str | None = None, count: int = 3) -> list[dict]:
    style_mood = music_library.auto_mood(style)
    out = []
    for item in music_library.list_library():
        mood, tid = item["mood"], item["id"]
        tempo = TEMPO.get(tid, 110.0)
        energy = 0.5 * MOOD_ENERGY[mood] + 0.5 * min(1.0, max(0.0, (tempo - 60) / 100))
        score = 1.0 - abs(profile["energy"] - energy)
        reasons = []
        if abs(profile["energy"] - energy) < 0.2:
            level = "fast-moving" if profile["energy"] > 0.6 else "steady" if profile["energy"] > 0.3 else "slow, calm"
            reasons.append(f"{tempo:.0f} BPM suits {level} footage")
        if mood_hint and mood == mood_hint:
            score += 1.0           # an explicit request always outranks what the footage alone suggests
            reasons.append(f"matches the {MOOD_WORDS[mood]} mood you asked for")
        if mood == style_mood:
            score += 0.2
            reasons.append("fits the editing style")
        if profile["speech"] > 0.5:
            if energy > 0.65:
                score -= 0.2
                reasons.append("busy: will be ducked under speech")
            elif energy < 0.5:
                score += 0.1
                reasons.append("soft enough to sit under speech")
        if not reasons:
            reasons.append(f"{MOOD_WORDS[mood]} {tempo:.0f} BPM track")
        out.append({**item, "tempo": tempo, "score": round(score, 3), "reason": (lambda t: t[0].upper() + t[1:] + ".")(", ".join(reasons)),
                    "suggestedVolume": 0.2 if profile["speech"] > 0.5 else 0.35})
    out.sort(key=lambda r: -r["score"])
    return out[:count]

"""Turn a plain-language request into a validated, reversible editing plan.

Deterministic and local: keyword/number rules, no model call. The plan is DATA (settings to change, a style, an
aspect, a template, notes and warnings). It is applied to the project document, so the usual undo/redo applies and
nothing here ever touches a file. Anything the text does not mention is left as it was.
"""
from __future__ import annotations

import re

from ..schemas import ProjectDoc
from . import templates

STYLE_WORDS = [   # explicit style names first; generic energy words last
    ("cinematic", ("cinematic", "film look", "movie")),
    ("vlog", ("vlog", "day in the life", "talking")),
    ("documentary", ("documentary", "interview", "storytelling")),
    ("professional", ("professional", "corporate", "business", "presentation")),
    ("minimal", ("minimal", "clean look", "simple", "understated")),
    ("energetic", ("energetic", "high energy", "fast-paced", "fast paced", "hype", "dynamic", "punchy", "fast cuts")),
]
MOOD_WORDS = [    # most specific first
    ("relaxing", ("calm", "relax", "chill", "peaceful", "soft", "gentle")),
    ("dramatic", ("dramatic", "intense", "tense", "suspense", "epic")),
    ("energetic", ("upbeat", "energetic", "hype", "pumped", "workout", "fast")),
    ("happy", ("happy", "joyful", "fun", "cheerful")),
    ("cinematic", ("cinematic", "inspiring", "emotional", "scenic")),
]
TEMPLATE_WORDS = [
    ("travel_recap", ("travel", "trip", "vacation", "holiday", "journey")),
    ("birthday_memories", ("birthday",)),
    ("product_showcase", ("product", "showcase", "advert", " ad ")),
    ("fitness_montage", ("fitness", "workout", "gym", "training")),
    ("social_reel", ("reel", "tiktok", "shorts")),
]
LANGUAGES = {"english": "en", "chinese": "zh", "malay": "ms", "spanish": "es", "french": "fr", "german": "de",
             "italian": "it", "portuguese": "pt", "russian": "ru", "japanese": "ja", "korean": "ko", "hindi": "hi",
             "arabic": "ar", "indonesian": "id", "tamil": "ta", "thai": "th", "turkish": "tr", "vietnamese": "vi"}


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def parse(instruction: str) -> dict:
    """Return {understood, settings, style, aspect, template, captionPreset, warnings}."""
    text = f" {(instruction or '').lower().strip()} "
    plan: dict = {"understood": [], "settings": {}, "style": None, "aspect": None, "template": None,
                  "captionPreset": None, "warnings": []}
    if not text.strip():
        return plan
    s, u = plan["settings"], plan["understood"]

    # length
    m = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?(?:minutes?|mins?)\b", text)
    sec = re.search(r"(\d+(?:\.\d+)?)\s*[- ]?(?:seconds?|secs?|s)\b", text)
    seconds = None
    if m:
        seconds = float(m.group(1)) * 60
    elif sec:
        seconds = float(sec.group(1))
    if seconds is not None:
        if seconds < 5 or seconds > 600:
            plan["warnings"].append(f"{seconds:g}s is outside 5-600s, so the length was left to the AI.")
        else:
            s["targetDuration"] = round(seconds)
            u.append(f"{round(seconds)} s long")

    # format
    if _has(text, ("vertical", "9:16", "reel", "tiktok", "shorts", "story")):
        plan["aspect"] = "9:16"
    elif _has(text, ("square", "1:1", "instagram post")):
        plan["aspect"] = "1:1"
    elif _has(text, ("youtube", "landscape", "16:9", "widescreen")):
        plan["aspect"] = "16:9"
    if plan["aspect"]:
        u.append(f"{plan['aspect']} format")

    # style
    for key, words in STYLE_WORDS:
        if _has(text, words):
            plan["style"] = key
            u.append(f"{key.capitalize()} style")
            break

    # template (structure), independent of style
    for key, words in TEMPLATE_WORDS:
        if _has(text, words):
            plan["template"] = key
            u.append(f"{templates.TEMPLATES[key]['name']} layout")
            break

    # music
    if _has(text, ("no music", "without music", "silent")):
        s["musicSource"] = "none"
        u.append("No music")
    elif "music" in text or _has(text, ("upbeat", "calm", "relaxing", "dramatic", "soundtrack")):
        s["musicSource"] = "auto"
        for mood, words in MOOD_WORDS:
            if _has(text, words):
                s["musicMood"] = mood
                break
        u.append(f"{s.get('musicMood', 'Matching')} music".capitalize() if s.get("musicMood") else "Matching music")

    # captions
    if _has(text, ("no captions", "without captions", "no subtitles")):
        s["captions"] = False
        u.append("No captions")
    elif _has(text, ("caption", "subtitle", "karaoke")):
        s["captions"] = True
        for preset in ("karaoke", "dynamic", "cinematic", "bold", "classic"):
            if preset in text:
                plan["captionPreset"] = preset
                break
        u.append(f"{(plan['captionPreset'] or 'Auto').capitalize()} captions")
        for name, code in LANGUAGES.items():
            if name in text:
                s["subtitleLanguage"] = code
                u.append(f"{name.capitalize()} speech")
                break

    # transitions / pace / cleaning
    if _has(text, ("no transitions", "hard cuts", "jump cuts")):
        s["transitions"] = False
        u.append("Hard cuts")
    elif _has(text, ("smooth transition", "transitions", "crossfade", "dissolve")):
        s["transitions"] = True
        u.append("Smooth transitions")
    if _has(text, ("keep everything", "keep all", "dont cut", "don't cut", "keep it all")):
        s["intensity"] = "light"
        u.append("Keep more footage")
    elif _has(text, ("tight", "snappy", "punchy", "trim hard", "short and sweet")):
        s["intensity"] = "aggressive"
        u.append("Tighter cuts")
    if _has(text, ("remove silence", "remove pauses", "cut pauses", "no dead air")):
        s["removeSilence"] = True
        u.append("Pauses removed")
    if _has(text, ("keep pauses", "keep silence")):
        s["removeSilence"] = False
        u.append("Pauses kept")
    return plan


def apply(doc: ProjectDoc, plan: dict) -> ProjectDoc:
    """Return a NEW document with the plan applied (validated by the schema); the input is not modified."""
    new = doc.model_copy(deep=True)
    patch = dict(plan.get("settings") or {})
    if plan.get("captionPreset"):
        patch["captionPreset"] = plan["captionPreset"]
    new.settings = new.settings.model_copy(update=patch)
    if plan.get("style"):
        new.style = plan["style"]
    if plan.get("aspect"):
        new.aspect = plan["aspect"]
    if plan.get("template"):
        tpl = templates.get(plan["template"])
        new.template = plan["template"]
        if tpl:
            if not plan.get("style") and new.style in ("auto", "dynamic"):
                new.style = tpl["suggestedStyle"]
            if not plan.get("aspect") and doc.aspect == "16:9" and plan["template"] != "travel_recap":
                new.aspect = tpl["aspect"]
            if "targetDuration" not in (plan.get("settings") or {}) and not new.settings.targetDuration:
                new.settings.targetDuration = tpl["duration"]
    return ProjectDoc.model_validate(new.model_dump())

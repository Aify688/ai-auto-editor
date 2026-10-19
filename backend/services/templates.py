"""Templates = reusable STRUCTURE (sections, text placeholders, suggested length and format).

Editing styles (services/editing.py STYLES) are the separate axis: pacing, transitions, colour, music mood and
caption look. Any template can be combined with any style, and a style works without a template.
"""
from __future__ import annotations

TEMPLATES: dict[str, dict] = {
    "travel_recap": {
        "name": "Travel Recap", "description": "Where you went, the highlights, and a sign-off.",
        "duration": 45, "aspect": "16:9", "suggestedStyle": "cinematic", "mood": "cinematic",
        "sections": [{"name": "Arrival", "weight": 2, "text": "Where we went"},
                     {"name": "Highlights", "weight": 5, "text": "The best moments"},
                     {"name": "Favourite view", "weight": 3, "text": "Favourite view"},
                     {"name": "Goodbye", "weight": 2, "text": "Until next time"}],
    },
    "birthday_memories": {
        "name": "Birthday Memories", "description": "A warm montage with a dedicated message.",
        "duration": 40, "aspect": "9:16", "suggestedStyle": "vlog", "mood": "happy",
        "sections": [{"name": "Intro", "weight": 2, "text": "Happy Birthday!"},
                     {"name": "Moments", "weight": 6, "text": "Favourite moments"},
                     {"name": "Wish", "weight": 2, "text": "Make a wish"}],
    },
    "product_showcase": {
        "name": "Product Showcase", "description": "Hook, features, and a call to action.",
        "duration": 20, "aspect": "1:1", "suggestedStyle": "energetic", "mood": "energetic",
        "sections": [{"name": "Hook", "weight": 2, "text": "Meet your new favourite"},
                     {"name": "Features", "weight": 5, "text": "Why you'll love it"},
                     {"name": "Call to action", "weight": 2, "text": "Get yours today"}],
    },
    "fitness_montage": {
        "name": "Fitness Montage", "description": "Fast, high-energy training highlights.",
        "duration": 30, "aspect": "9:16", "suggestedStyle": "energetic", "mood": "energetic",
        "sections": [{"name": "Warm-up", "weight": 2, "text": "Warm up"},
                     {"name": "Training", "weight": 6, "text": "No excuses"},
                     {"name": "Finish", "weight": 2, "text": "Finish strong"}],
    },
    "social_reel": {
        "name": "Social Media Reel", "description": "Short vertical hook-first reel.",
        "duration": 15, "aspect": "9:16", "suggestedStyle": "energetic", "mood": "happy",
        "sections": [{"name": "Hook", "weight": 2, "text": ""},
                     {"name": "Body", "weight": 6, "text": ""},
                     {"name": "Outro", "weight": 1, "text": "Follow for more"}],
    },
}


def get(template_id: str | None) -> dict | None:
    t = TEMPLATES.get(template_id) if template_id else None
    return {"id": template_id, **t} if t else None


def list_all() -> list[dict]:
    return [{"id": k, **{x: v[x] for x in ("name", "description", "duration", "aspect", "suggestedStyle", "mood")},
             "sections": [{"name": s["name"], "weight": s["weight"], "text": s["text"]} for s in v["sections"]]}
            for k, v in TEMPLATES.items()]


def lay_out(template: dict, clips: list[dict], total: float) -> tuple[dict, list[dict]]:
    """Split the finished timeline into the template's sections (snapped to clip boundaries) and return
    (EDL `template` record, title placeholders at each section start). Never reorders or drops clips."""
    from .layout import layout as lay_layout

    sections = template["sections"]
    if not clips or total <= 0:
        return {"id": template.get("id"), "name": template["name"], "sections": []}, []
    starts = [c["outStart"] for c in lay_layout(clips, None)["clips"]]
    weight_sum = float(sum(s["weight"] for s in sections))
    bounds, acc = [], 0.0
    for s in sections:
        bounds.append(total * acc / weight_sum)
        acc += s["weight"]
    snapped = []
    for b in bounds:
        snapped.append(min(starts, key=lambda x: abs(x - b)) if starts else 0.0)
    last = None
    for i in range(len(snapped)):                    # strictly increasing; collapse sections that snap together
        if last is not None and snapped[i] <= last + 1e-6:
            snapped[i] = None
        else:
            last = snapped[i]
    record, titles = [], []
    keep = [(s, b) for s, b in zip(sections, snapped) if b is not None]
    for i, (s, b) in enumerate(keep):
        end = keep[i + 1][1] if i + 1 < len(keep) else total
        record.append({"name": s["name"], "start": round(b, 3), "end": round(end, 3)})
        if s["text"]:
            titles.append({"text": s["text"], "start": round(b, 3), "duration": round(max(0.8, min(2.5, (end - b) * 0.8)), 3),
                           "position": "center" if i == 0 else "bottom"})
    return {"id": template.get("id"), "name": template["name"], "sections": record}, titles

"""Output-timeline layout of an EDL (mirrors frontend/src/lib/layout.ts and engine grouping)."""
from __future__ import annotations

from typing import Iterable


def group_indexes(clips: list[dict]) -> list[int]:
    out, g = [], -1
    for i, c in enumerate(clips):
        if i == 0 or c["mediaId"] != clips[i - 1]["mediaId"] or c.get("sceneBreak"):
            g += 1
        out.append(g)
    return out


def effective_transition(clips: list[dict], transition: dict | None) -> float:
    if not transition or len(clips) < 2:
        return 0.0
    groups = group_indexes(clips)
    n = groups[-1] + 1
    if n < 2:
        return 0.0
    durs = [0.0] * n
    for c, g in zip(clips, groups):
        durs[g] += c["srcEnd"] - c["srcStart"]
    fit = round(min(float(transition["duration"]), min(durs) / 2 - 0.05), 2)
    return 0.0 if fit < 0.15 else fit


def layout(clips: list[dict], transition: dict | None) -> dict:
    d = effective_transition(clips, transition)
    groups = group_indexes(clips)
    laid, acc, t = [], 0.0, 0.0
    for i, c in enumerate(clips):
        if i > 0 and groups[i] != groups[i - 1]:
            t = acc - d
        dur = c["srcEnd"] - c["srcStart"]
        laid.append({"index": i, "group": groups[i], "outStart": round(t, 3), "outEnd": round(t + dur, 3)})
        t += dur
        acc = t
    return {"clips": laid, "duration": round(acc, 3), "transition": d}


def caption_spans(captions: Iterable[dict], clips: list[dict], laid: list[dict]) -> list[dict]:
    out = []
    for cap in captions:
        for c, lc in zip(clips, laid):
            if c["mediaId"] != cap["mediaId"]:
                continue
            lo, hi = max(c["srcStart"], cap["srcStart"]), min(c["srcEnd"], cap["srcEnd"])
            if hi - lo > 0.05:
                out.append({"id": cap["id"], "outStart": round(lc["outStart"] + lo - c["srcStart"], 3),
                            "outEnd": round(lc["outStart"] + hi - c["srcStart"], 3), "text": cap["text"]})
    return sorted(out, key=lambda x: x["outStart"])

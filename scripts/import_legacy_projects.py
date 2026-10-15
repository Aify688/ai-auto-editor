#!/usr/bin/env python3
"""Import projects saved by the original Streamlit editor (projects/*.json) into FrameFlow.

Talks to the running app over its HTTP API, so it needs `./start.sh` to be up.
Nothing is deleted or modified: source media is uploaded as a copy, the legacy JSON stays where it is,
and imported ids are recorded in data/legacy_imported.json so re-running never duplicates a project.

    python3 scripts/import_legacy_projects.py [--url http://localhost:8000]
"""
import argparse
import json
import mimetypes
import sys
import time
import uuid
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DONE_FILE = ROOT / "data" / "legacy_imported.json"
STYLES = {"dynamic", "cinematic", "vlog"}


def call(base, method, path, body=None, headers=None):
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=300) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def post_json(base, method, path, payload):
    return call(base, method, path, json.dumps(payload).encode(), {"Content-Type": "application/json"})


def upload(base, pid, file: Path):
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{file.name}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode()
    body = head + file.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return call(base, "POST", f"/api/projects/{pid}/media", body,
                {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def convert(legacy: dict, media_ids: list):
    exp = legacy.get("export", {})
    style = legacy.get("preset") if legacy.get("preset") in STYLES else "dynamic"
    aspect = exp.get("aspect") if exp.get("aspect") in ("16:9", "9:16", "1:1") else "16:9"
    skills = legacy.get("skills", {})
    look = skills.get("color.look", {}).get("look", "none")
    if look not in ("none", "warm", "cool", "cinematic", "vivid", "bw", "faded"):
        look = "none"
    lufs = skills.get("audio.loudnorm", {}).get("target_lufs", -14)
    clips = []
    for i, seg in enumerate(legacy.get("segments", [])):
        idx = seg.get("clip", 0)
        if idx >= len(media_ids) or media_ids[idx] is None or seg["end"] <= seg["start"]:
            continue
        clips.append({"id": f"c{uuid.uuid4().hex[:8]}", "mediaId": media_ids[idx], "srcStart": seg["start"],
                      "srcEnd": seg["end"], "sceneBreak": True, "label": f"Segment {i + 1}",
                      "focusX": 0.5, "focusY": 0.5, "score": None})
    edl = {"version": 1, "style": style, "aspect": aspect, "fit": exp.get("fit", "crop") if exp.get("fit") in ("crop", "blur") else "crop",
           "clips": clips, "transition": None, "look": look, "music": None, "captions": [], "burnCaptions": True,
           "titles": [], "audio": {"normalize": True, "lufs": max(-30, min(-9, lufs)), "clean": False, "fades": False},
           "beat": None, "notes": ["Imported from the original Streamlit editor."] + legacy.get("notes", [])}
    doc = {"style": style, "aspect": aspect, "edl": edl,
           "export": {"filename": "imported-edit", "resolution": 1080 if exp.get("short_edge", 1080) >= 1080 else 720,
                      "fps": exp.get("fps") if exp.get("fps") in (24, 25, 30, 60) else 30, "quality": "standard"}}
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    base = ap.parse_args().url.rstrip("/")
    done = set(json.loads(DONE_FILE.read_text())) if DONE_FILE.exists() else set()
    files = sorted((ROOT / "projects").glob("*.json"))
    if not files:
        print("No legacy projects found in projects/.")
        return
    for f in files:
        legacy = json.loads(f.read_text())
        lid = legacy.get("id", f.stem)
        if lid in done:
            print(f"skip   {f.name} (already imported)")
            continue
        sources = [Path(p) for p in legacy.get("sources", [])]
        proj = post_json(base, "POST", "/api/projects", {"name": (legacy.get("name") or "Imported project")[:110] + " (imported)"})
        media_ids = []
        for src in sources:
            if not src.exists():
                print(f"  warn: missing source {src}")
                media_ids.append(None)
                continue
            media_ids.append(upload(base, proj["id"], src)["id"])
        for _ in range(120):  # wait for ingest so the clips resolve to ready media
            items = {m["id"]: m for m in call(base, "GET", f"/api/projects/{proj['id']}/media")}
            if all(i is None or items.get(i, {}).get("status") != "processing" for i in media_ids):
                break
            time.sleep(1)
        doc = convert(legacy, media_ids)
        post_json(base, "PUT", f"/api/projects/{proj['id']}", {"doc": doc})
        done.add(lid)
        DONE_FILE.parent.mkdir(exist_ok=True)
        DONE_FILE.write_text(json.dumps(sorted(done)))
        print(f"import {f.name} -> project {proj['id']} ({len(doc['edl']['clips'])} clips)")


if __name__ == "__main__":
    sys.exit(main())

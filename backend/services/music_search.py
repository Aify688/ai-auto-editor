"""Searchable music for videos: the bundled CC BY library plus Jamendo, a real catalogue of Creative Commons music.

Jamendo needs a free client id (JAMENDO_CLIENT_ID in .env). Without it only the bundled tracks are searchable, and the
UI says what to set up; uploads keep working either way. The client id and every provider URL stay on the server:
the browser previews through /api/music/preview/{id}, and a chosen track is downloaded into the project's media.

Licences are shown for every result. Tracks whose licence forbids commercial use (NC) or adaptation (ND) are hidden
unless the caller asks for them, and are refused when added, because exported videos are often published.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import media as media_svc
from . import music_library
from ..workers.jobs import JobFailed

JAMENDO_BASE = "https://api.jamendo.com/v3.0"
SETUP_HINT = ("Search for more music needs a Jamendo client id (free): create an app at "
              "https://devportal.jamendo.com, add JAMENDO_CLIENT_ID=<your client id> to the .env file in the project "
              "folder, then restart ./start.sh. The bundled tracks and your own uploads work without it.")
LIBRARY_GENRE = "Instrumental"


class MusicError(Exception):
    pass


def _cfg() -> dict:
    env = os.environ.get
    return {"client_id": env("JAMENDO_CLIENT_ID", "").strip(), "base": env("JAMENDO_BASE_URL", JAMENDO_BASE).rstrip("/")}


def status() -> dict:
    ok = bool(_cfg()["client_id"])
    return {"providers": [
        {"id": "library", "name": "Bundled library", "configured": True, "tracks": len(music_library.list_library()),
         "license": "CC BY 4.0, commercial use allowed, credit required"},
        {"id": "jamendo", "name": "Jamendo", "configured": ok,
         "license": "Creative Commons, varies per track (shown on every result)", "hint": None if ok else SETUP_HINT}]}


# ------------------------------------------------------------------ licences
def parse_license(url: str | None) -> dict:
    """'https://creativecommons.org/licenses/by-nc-sa/3.0/' -> label, commercialOk, adaptOk."""
    m = re.search(r"/licenses/([a-z\-]+)/([\d.]+)", url or "")
    if not m:
        return {"label": "Unknown licence", "url": url, "commercialOk": False, "adaptOk": False}
    parts = m.group(1).split("-")
    return {"label": f"CC {m.group(1).upper()} {m.group(2)}", "url": url,
            "commercialOk": "nc" not in parts, "adaptOk": "nd" not in parts}


def attribution_line(title: str, artist: str, lic: dict, source_url: str | None) -> str:
    s = f"“{title}” by {artist}"
    if lic.get("label") and lic["label"] != "Unknown licence":
        s += f", licensed under {lic['label']}"
    if lic.get("url"):
        s += f" ({lic['url']})"
    if source_url:
        s += f". Source: {source_url}"
    return s


# ------------------------------------------------------------------ bundled library
def _library_results(q: str) -> list[dict]:
    tokens = [t for t in re.split(r"\s+", q.lower().strip()) if t]
    out = []
    for t in music_library.list_library():
        lic = parse_license("https://creativecommons.org/licenses/by/4.0/")
        hay = " ".join([t["title"], "tanner helland", LIBRARY_GENRE, t["mood"]]).lower()
        if tokens and not all(tok in hay for tok in tokens):
            continue
        out.append({"id": t["id"], "provider": "library", "title": t["title"], "artist": "Tanner Helland",
                    "duration": t["duration"], "genres": [LIBRARY_GENRE.lower()], "moods": [t["mood"]],
                    "license": lic, "previewUrl": t["url"],
                    "attribution": attribution_line(t["title"], "Tanner Helland", lic,
                                                    "https://github.com/tannerhelland/free-music")})
    return out


# ------------------------------------------------------------------ Jamendo
def _get(path: str, params: dict) -> dict:
    c = _cfg()
    q = urllib.parse.urlencode({"client_id": c["client_id"], "format": "json", **params})
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{c['base']}{path}?{q}", headers={"Accept": "application/json"}),
                                    timeout=20) as r:
            data = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise MusicError(f"Jamendo returned an error ({e.code}). Check JAMENDO_CLIENT_ID in .env." if e.code in (401, 403)
                         else f"Jamendo returned an error ({e.code}).")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise MusicError(f"Could not reach Jamendo: {getattr(e, 'reason', e)}")
    hdr = data.get("headers") or {}
    if hdr.get("status") == "failed":
        raise MusicError(f"Jamendo: {hdr.get('error_message') or 'request failed'}")
    return data


def _jamendo_track(t: dict) -> dict:
    lic = parse_license(t.get("license_ccurl"))
    tags = ((t.get("musicinfo") or {}).get("tags") or {})
    title, artist = t.get("name") or "Untitled", t.get("artist_name") or "Unknown artist"
    return {"id": f"jamendo:{t['id']}", "provider": "jamendo", "title": title, "artist": artist,
            "duration": float(t.get("duration") or 0), "genres": [g.lower() for g in tags.get("genres") or []],
            "moods": [m.lower() for m in tags.get("vartags") or []], "license": lic,
            "previewUrl": f"/api/music/preview/jamendo:{t['id']}",
            "attribution": attribution_line(title, artist, lic, t.get("shareurl"))}


def _jamendo_search(q: str, limit: int) -> list[dict]:
    base = {"limit": limit, "include": "musicinfo", "audioformat": "mp32", "order": "popularity_total"}
    found: dict[str, dict] = {}
    queries = [{"search": q}]
    tags = "+".join(re.split(r"\s+", q.strip()))
    if tags:
        queries.append({"fuzzytags": tags})                    # genre / mood words ("calm", "rock", "happy")
    for extra in queries:
        for t in _get("/tracks/", {**base, **extra}).get("results") or []:
            found.setdefault(str(t["id"]), t)
    return [_jamendo_track(t) for t in found.values()]


def search(q: str, include_restricted: bool = False, limit: int = 24) -> dict:
    """{results, notices}. Bundled tracks first; Jamendo appended when configured."""
    q = (q or "").strip()
    results, notices = _library_results(q), []
    if _cfg()["client_id"]:
        try:
            for r in _jamendo_search(q, 40 if not include_restricted else limit):
                results.append(r)
        except MusicError as e:
            notices.append(str(e))
    else:
        notices.append(SETUP_HINT)
    hidden = 0
    if not include_restricted:
        kept = [r for r in results if r["license"]["commercialOk"] and r["license"]["adaptOk"]]
        hidden = len(results) - len(kept)
        results = kept
    if hidden:
        notices.append(f"{hidden} track(s) hidden because their licence does not allow commercial use or editing.")
    return {"results": results[:limit], "notices": notices}


def preview_source(track_id: str) -> str:
    """The provider's real stream URL for a Jamendo track (kept on the server)."""
    if not track_id.startswith("jamendo:"):
        raise MusicError("Unknown track.")
    data = _get("/tracks/", {"id": track_id.split(":", 1)[1], "audioformat": "mp32"})
    res = data.get("results") or []
    if not res or not res[0].get("audio"):
        raise MusicError("That track has no preview.")
    return res[0]["audio"]


def add_to_project(pid: str, track_id: str, allow_restricted: bool = False) -> dict:
    """Bundled track -> {"mediaId": "lib:..."} (nothing to download). Jamendo track -> downloaded into the project's media
    with its attribution stored, so exports can credit it."""
    if music_library.is_library_id(track_id):
        t = next((x for x in _library_results("") if x["id"] == track_id), None)
        if t is None:
            raise MusicError("Unknown track.")
        return {"mediaId": track_id, "media": None, "attribution": t["attribution"], "license": t["license"]}
    if not track_id.startswith("jamendo:"):
        raise MusicError("Unknown track.")
    if not _cfg()["client_id"]:
        raise MusicError(SETUP_HINT)
    data = _get("/tracks/", {"id": track_id.split(":", 1)[1], "include": "musicinfo", "audioformat": "mp32"})
    res = data.get("results") or []
    if not res:
        raise MusicError("That track was not found.")
    t = _jamendo_track(res[0])
    lic = t["license"]
    if not allow_restricted and not (lic["commercialOk"] and lic["adaptOk"]):
        raise MusicError(f"This track is licensed {lic['label']}, which does not allow commercial use or editing, so it "
                         "cannot be added to a video you may publish.")
    from .. import db
    for m in media_svc.list_media(pid):                         # already in this project: reuse it, never duplicate
        if (m["info"].get("attribution") or {}).get("trackId") == track_id and m["status"] != "error":
            return {"mediaId": m["id"], "media": None, "attribution": t["attribution"], "license": lic}
    audio = res[0].get("audio")
    if not audio:
        raise MusicError("That track cannot be downloaded.")
    import tempfile
    safe = re.sub(r"[^\w .\-]", "", f"{t['title']} - {t['artist']}")[:80].strip() or "Track"
    try:
        with urllib.request.urlopen(urllib.request.Request(audio), timeout=120) as r, tempfile.TemporaryFile() as tmp:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.seek(0)
            item = media_svc.save_upload(pid, f"{safe}.mp3", tmp)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise MusicError(f"Could not download the track: {getattr(e, 'reason', e)}")
    except media_svc.MediaError as e:
        raise MusicError(f"The downloaded file could not be used: {e}")
    row = media_svc.get_row(item["id"])
    info = db.loads(row["info"], {})
    info["attribution"] = {"text": t["attribution"], "license": lic["label"], "licenseUrl": lic["url"],
                           "title": t["title"], "artist": t["artist"], "source": "Jamendo", "trackId": track_id}
    db.execute("UPDATE media SET info=? WHERE id=?", (db.dumps(info), item["id"]))
    return {"mediaId": item["id"], "media": media_svc.get(item["id"]), "attribution": t["attribution"], "license": lic}


def credits_for(clips: list[dict]) -> list[str]:
    """Attribution lines for every credited track used in the timeline (deduplicated, in order)."""
    seen, out = set(), []
    for c in clips:
        mid = c.get("mediaId")
        line = None
        if mid and music_library.is_library_id(mid):
            line = next((x["attribution"] for x in _library_results("") if x["id"] == mid), None)
        elif mid:
            row = media_svc.get_row(mid)
            if row:
                from .. import db
                line = ((db.loads(row["info"], {}) or {}).get("attribution") or {}).get("text")
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out

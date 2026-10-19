"""Text-to-video: turn a written description into original footage with a real provider.

The provider speaks the Replicate-style prediction API (create -> poll -> download). Nothing here fakes
output: when no provider is configured the job fails with a setup message, and a provider error is surfaced
as-is. The API token is read from the environment on the server and never sent to the browser.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.request

from . import media as media_svc
from ..workers.jobs import JobFailed

DEFAULT_BASE = "https://api.replicate.com/v1"
DEFAULT_MODEL = "minimax/video-01"
PROMPT_LIMIT = 1800          # characters one provider request can take
SETUP_HINT = ("Text-to-video needs a provider. Add REPLICATE_API_TOKEN=<your token> to the .env file in the "
              "project folder (optionally FRAMEFLOW_T2V_MODEL), then restart ./start.sh.")


def _cfg() -> dict:
    env = os.environ.get
    return {
        "token": env("REPLICATE_API_TOKEN", "").strip(),
        "base": env("FRAMEFLOW_T2V_BASE_URL", DEFAULT_BASE).rstrip("/"),
        "model": env("FRAMEFLOW_T2V_MODEL", DEFAULT_MODEL).strip(),
        "clip_seconds": float(env("FRAMEFLOW_T2V_CLIP_SECONDS", "6")),
        "max_scenes": int(env("FRAMEFLOW_T2V_MAX_SCENES", "12")),
        "timeout": float(env("FRAMEFLOW_T2V_TIMEOUT", "900")),
        "poll": float(env("FRAMEFLOW_T2V_POLL", "3")),
        "input": env("FRAMEFLOW_T2V_INPUT", '{"prompt": "{prompt}"}'),
    }


def status() -> dict:
    """Public status for the UI. Never includes the token."""
    c = _cfg()
    ok = bool(c["token"])
    return {"configured": ok, "provider": "Replicate", "model": c["model"], "clipSeconds": c["clip_seconds"],
            "maxScenes": c["max_scenes"], "promptLimit": PROMPT_LIMIT,
            "maxSeconds": round(c["clip_seconds"] * c["max_scenes"], 1),
            "hint": None if ok else SETUP_HINT}


# ------------------------------------------------------------------ planning
def _units(text: str) -> list[str]:
    """Paragraphs / numbered lines first; any unit still over the limit is split on sentences, then words."""
    parts = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\s*(?:\d+[.)]|[-*•])\s)", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        p = re.sub(r"\s+", " ", p)
        while len(p) > PROMPT_LIMIT:
            cut = max(p.rfind(". ", 0, PROMPT_LIMIT), p.rfind("! ", 0, PROMPT_LIMIT), p.rfind("? ", 0, PROMPT_LIMIT))
            cut = cut + 1 if cut > PROMPT_LIMIT // 3 else p.rfind(" ", 0, PROMPT_LIMIT)
            cut = cut if cut > 0 else PROMPT_LIMIT
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def plan(instruction: str, target: float | None = None, aspect: str = "16:9") -> dict:
    """Split the description into scenes without dropping any of it. Raises JobFailed when it cannot fit."""
    c = _cfg()
    text = (instruction or "").strip()
    if not text:
        raise JobFailed("Describe the video you want to generate.")
    units = _units(text)
    notes: list[str] = []
    wanted = len(units)
    if target:
        wanted = max(1, round(target / c["clip_seconds"]))
        if wanted > c["max_scenes"]:
            notes.append(f"Requested {target:.0f}s, but the provider is limited to {c['max_scenes']} scenes of "
                         f"{c['clip_seconds']:g}s: generating {c['max_scenes'] * c['clip_seconds']:g}s instead.")
    n = max(1, min(wanted, c["max_scenes"]))
    if len(units) < n:           # too few paragraphs for the length asked: use sentences as scene beats
        sentences = [x.strip() for u in units for x in re.split(r"(?<=[.!?])\s+", u) if x.strip()]
        if len(sentences) > len(units):
            units = sentences
    if target and len(units) < n:
        n = len(units)
        notes.append(f"Your description has {n} distinct scene(s), so {n * c['clip_seconds']:g}s is generated instead of "
                     f"{target:.0f}s. Describe more scenes to make it longer.")
    # Greedy contiguous packing: balance characters across n scenes, never exceeding the request limit.
    total = sum(len(u) + 1 for u in units)
    scenes: list[str] = []
    cur: list[str] = []
    size = 0
    goal = math.ceil(total / n)
    for u in units:
        if cur and (size + len(u) + 1 > PROMPT_LIMIT or (size >= goal and len(scenes) < n - 1)):
            scenes.append(" ".join(cur))
            cur, size = [], 0
        cur.append(u)
        size += len(u) + 1
    if cur:
        scenes.append(" ".join(cur))
    if len(scenes) > c["max_scenes"]:
        raise JobFailed(f"This description is too long for the provider: it needs {len(scenes)} scenes but at most "
                        f"{c['max_scenes']} (about {c['max_scenes'] * PROMPT_LIMIT:,} characters) can be generated at "
                        "once. Shorten it or split it into several videos.")
    if len(units) > len(scenes):
        notes.append(f"{len(units)} paragraphs were grouped into {len(scenes)} scenes to stay within the "
                     "provider's limits; no text was dropped.")
    seconds = round(len(scenes) * c["clip_seconds"], 1)
    return {"scenes": scenes, "sceneCount": len(scenes), "clipSeconds": c["clip_seconds"], "seconds": seconds,
            "chars": len(text), "aspect": aspect, "notes": notes, "limits": {
                "maxScenes": c["max_scenes"], "promptLimit": PROMPT_LIMIT}}


# ------------------------------------------------------------------ provider client
def _http(method: str, url: str, token: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            raw = json.loads(e.read() or b"{}")
            detail = raw.get("detail") or raw.get("title") or raw.get("error") or ""
        except Exception:
            pass
        if e.code in (401, 403):
            raise JobFailed("The video provider rejected the API token. Check REPLICATE_API_TOKEN in .env.")
        if e.code == 402:
            raise JobFailed("The video provider reports insufficient credit. Add credit to your account and retry.")
        if e.code == 429:
            raise JobFailed("The video provider is rate-limiting requests. Wait a minute and try again.")
        raise JobFailed(f"The video provider returned an error ({e.code}): {detail or e.reason}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JobFailed(f"Could not reach the video provider: {getattr(e, 'reason', e)}")


def _fill(node, values: dict):
    if isinstance(node, str):
        return values[node] if node in values else node
    if isinstance(node, list):
        return [_fill(x, values) for x in node]
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    return node


def _input(c: dict, prompt: str, aspect: str) -> dict:
    try:
        tpl = json.loads(c["input"])
    except ValueError:
        raise JobFailed("FRAMEFLOW_T2V_INPUT in .env is not valid JSON.")
    return _fill(tpl, {"{prompt}": prompt, "{aspect}": aspect, "{seconds}": c["clip_seconds"]})


def generate_scene(prompt: str, aspect: str, check, *, model: str | None = None, body: dict | None = None,
                   setup_hint: str = SETUP_HINT) -> str:
    """Run one prediction to completion and return the output URL. `check()` raises on cancel.
    `model` and `body` (the provider's `input`) override the text-to-video defaults, e.g. for image-to-video."""
    c = _cfg()
    if not c["token"]:
        raise JobFailed(setup_hint)
    pred = _http("POST", f"{c['base']}/models/{model or c['model']}/predictions", c["token"],
                 {"input": body if body is not None else _input(c, prompt, aspect)})
    get_url = (pred.get("urls") or {}).get("get") or f"{c['base']}/predictions/{pred.get('id')}"
    cancel_url = (pred.get("urls") or {}).get("cancel")
    deadline = time.time() + c["timeout"]
    try:
        while pred.get("status") not in ("succeeded", "failed", "canceled"):
            if time.time() > deadline:
                raise JobFailed(f"The video provider took longer than {c['timeout']:.0f}s for one scene.")
            check()
            time.sleep(c["poll"])
            pred = _http("GET", get_url, c["token"])
    except BaseException:
        if cancel_url and pred.get("status") not in ("succeeded", "failed", "canceled"):
            try:
                _http("POST", cancel_url, c["token"], {}, timeout=10)
            except Exception:
                pass
        raise
    if pred["status"] != "succeeded":
        raise JobFailed(f"The video provider could not generate a scene: {pred.get('error') or pred['status']}")
    out = pred.get("output")
    url = out[0] if isinstance(out, list) and out else out
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise JobFailed("The video provider finished but returned no video file.")
    return url


def download(url: str, pid: str, name: str) -> dict:
    """Fetch a generated clip into the project's media library (status 'processing')."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=120) as r, \
                tempfile.TemporaryFile() as tmp:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                tmp.write(chunk)
            tmp.seek(0)
            return media_svc.save_upload(pid, name, tmp)
    except media_svc.MediaError as e:
        raise JobFailed(f"The provider's video could not be used: {e}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise JobFailed(f"Could not download the generated video: {getattr(e, 'reason', e)}")

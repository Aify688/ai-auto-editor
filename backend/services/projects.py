"""Project CRUD. The project document (settings + EDL + export settings) is stored as JSON."""
from __future__ import annotations

import shutil
import time
import uuid

from .. import config, db
from ..schemas import ProjectDoc


class NotFound(LookupError):
    pass


# How many past generated versions to keep per project. Older ones (and their preview
# files, see pipeline._render_preview) are dropped so disk use stays bounded, but a
# regenerate never destroys the version that was current until this cap is hit.
MAX_HISTORY = 8


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _row_to_project(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "doc": ProjectDoc.model_validate(db.loads(row["doc"], {})).model_dump(),
        "render": db.loads(row["render"]),
        "history": db.loads(row["history"], []),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def create(name: str) -> dict:
    pid = new_id()
    now = time.time()
    db.execute("INSERT INTO projects (id, name, doc, render, history, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
               (pid, name.strip() or "Untitled project", db.dumps(ProjectDoc().model_dump()), None, "[]", now, now))
    for sub in ("media", "cache", "renders", "exports"):
        (config.project_dir(pid) / sub).mkdir(parents=True, exist_ok=True)
    return get(pid)


def get(pid: str) -> dict:
    row = db.one("SELECT * FROM projects WHERE id=?", (pid,))
    if row is None:
        raise NotFound(f"Project {pid} not found")
    return _row_to_project(row)


def list_all() -> list[dict]:
    rows = db.query("""
        SELECT p.id, p.name, p.created_at, p.updated_at, p.render,
               (SELECT COUNT(*) FROM media m WHERE m.project_id = p.id) AS media_count,
               (SELECT m.id FROM media m WHERE m.project_id = p.id AND m.kind != 'audio'
                AND m.status = 'ready' ORDER BY m.position LIMIT 1) AS cover_media
        FROM projects p ORDER BY p.updated_at DESC""")
    out = []
    for r in rows:
        render = db.loads(r["render"])
        cover = None
        if r["cover_media"]:
            m = db.one("SELECT info FROM media WHERE id=?", (r["cover_media"],))
            cover = (db.loads(m["info"], {}) if m else {}).get("thumbUrl")
        out.append({"id": r["id"], "name": r["name"], "createdAt": r["created_at"], "updatedAt": r["updated_at"],
                    "mediaCount": r["media_count"], "coverUrl": cover,
                    "hasRender": bool(render), "renderDuration": (render or {}).get("duration")})
    return out


def update(pid: str, name: str | None = None, doc: ProjectDoc | None = None) -> dict:
    get(pid)
    now = time.time()
    if name is not None:
        db.execute("UPDATE projects SET name=?, updated_at=? WHERE id=?", (name.strip(), now, pid))
    if doc is not None:
        db.execute("UPDATE projects SET doc=?, updated_at=? WHERE id=?", (db.dumps(doc.model_dump()), now, pid))
    return get(pid)


def set_render(pid: str, render: dict | None) -> list[dict]:
    """Make `render` the current version. The previous current version (if any) is kept in
    history rather than discarded, up to MAX_HISTORY entries. Returns the dropped entries
    (if the cap was hit) so the caller can clean up their preview files."""
    proj = get(pid)
    history = list(proj["history"] or [])
    prev = proj["render"]
    if prev and prev.get("id") and prev["id"] != (render or {}).get("id"):
        history.insert(0, prev)
    dropped = history[MAX_HISTORY:]
    history = history[:MAX_HISTORY]
    db.execute("UPDATE projects SET render=?, history=?, updated_at=? WHERE id=?",
               (db.dumps(render) if render else None, db.dumps(history), time.time(), pid))
    return dropped


def restore_render(pid: str, version_id: str) -> dict:
    """Make a past version current again, moving the current one into history instead of
    losing it. Raises NotFound if `version_id` isn't the current render or in history."""
    proj = get(pid)
    if proj["render"] and proj["render"].get("id") == version_id:
        return proj["render"]
    history = list(proj["history"] or [])
    match = next((h for h in history if h.get("id") == version_id), None)
    if match is None:
        raise NotFound(f"Version {version_id} not found")
    history.remove(match)
    if proj["render"]:
        history.insert(0, proj["render"])
    history = history[:MAX_HISTORY]
    db.execute("UPDATE projects SET render=?, history=?, updated_at=? WHERE id=?",
               (db.dumps(match), db.dumps(history), time.time(), pid))
    return match


def delete(pid: str) -> None:
    get(pid)
    db.execute("DELETE FROM jobs WHERE project_id=?", (pid,))
    db.execute("DELETE FROM media WHERE project_id=?", (pid,))
    db.execute("DELETE FROM projects WHERE id=?", (pid,))
    folder = config.project_dir(pid)
    # Only ever remove a folder inside our own projects directory.
    if folder.resolve().parent == config.PROJECTS_DIR.resolve() and folder.exists():
        shutil.rmtree(folder, ignore_errors=True)

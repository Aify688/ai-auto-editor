"""FrameFlow API server.

Run from the project root:
    .venv/bin/uvicorn backend.main:app --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import jobs as jobs_api
from .api import media as media_api
from .api import projects, system
from .services import media as media_svc
from .services import pipeline  # noqa: F401  (registers job handlers)
from .workers import jobs


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.connect()
    jobs.fail_interrupted()
    for mid in media_svc.pending_ids():  # uploads whose processing was cut short by a restart
        row = media_svc.get_row(mid)
        jobs.submit("ingest", row["project_id"], {"mediaId": mid})
    yield


app = FastAPI(title="FrameFlow", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])

for module in (projects, system, media_api, jobs_api):
    app.include_router(module.router)
app.include_router(projects.router_templates)

config.ensure_dirs()
# Project media, proxies, renders and exports. StaticFiles answers HTTP Range requests, so video seeking works.
app.mount("/files", StaticFiles(directory=str(config.DATA_DIR)), name="files")
# The bundled, CC-BY-licensed background-music library (see backend/assets/music/CREDITS.md).
app.mount("/music-library", StaticFiles(directory=str(config.ROOT / "backend" / "assets" / "music")),
         name="music-library")

# Serve the built frontend when it exists (single-command local run).
if (config.FRONTEND_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(config.FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # An unknown API/file path is an error, not the web page: otherwise a client that asks an older or
        # misrouted server for JSON gets a 200 "<!doctype html>" and fails with "Unexpected token '<'".
        if path.split("/", 1)[0] in ("api", "files", "music-library"):
            raise HTTPException(404, f"No such endpoint: /{path}. If the app was updated, restart the server (./start.sh).")
        target = config.FRONTEND_DIST / path
        if path and target.is_file() and config.FRONTEND_DIST in target.resolve().parents:
            return FileResponse(target)
        return FileResponse(config.FRONTEND_DIST / "index.html")

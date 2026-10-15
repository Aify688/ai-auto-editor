# FrameFlow: AI Auto Video Editor

Local, CapCut-style desktop editor that cuts a video for you. React + TypeScript + Tailwind UI,
FastAPI backend, FFmpeg rendering, SQLite persistence. No paid services or API keys.

> **One app, one URL: http://localhost:8000.** `./start.sh` is the only thing you need to run. It serves the API, media
> and the React UI from a single process (no second server, no Node dev server). The original Streamlit editor
> (`streamlit run app.py`, port 8501) is kept in the repo as a legacy tool and is no longer part of the normal workflow;
> bring its saved projects into the app with `python3 scripts/import_legacy_projects.py` (copies, never deletes).

## Quick start

```bash
brew install ffmpeg            # macOS (see ffmpeg.org for other systems)
./start.sh                     # creates .venv, installs deps, builds the UI, serves http://localhost:8000
                               # (uses the next free port if 8000 is taken; or set PORT=8123)
```

Development (hot reload): `.venv/bin/uvicorn backend.main:app --reload --port 8000` and, in `frontend/`,
`npm install && npm run dev` (http://localhost:5173, proxies `/api` and `/files` to port 8000).
Config: copy `.env.example` to `.env`. Data lives in `data/` (SQLite db at `data/frameflow.db`, created automatically).

## How it works

Upload -> analyze -> plan edit -> timeline (EDL) -> render -> preview -> export

| Stage | Implementation (all local, deterministic unless noted) |
|---|---|
| Metadata, thumbnails, proxies, waveforms | FFprobe / FFmpeg |
| Scene detection | PySceneDetect ContentDetector |
| Motion, sharpness, faces, motion centroid | OpenCV (frame difference, Laplacian variance, Haar cascade) |
| Silence | FFmpeg `silencedetect` + RMS energy |
| Highlight selection | Weighted score per style (see `backend/services/editing.py`), repetition cap per scene |
| Beat sync (Dynamic + music) | Onset-envelope autocorrelation (`backend/services/beats.py`) |
| Captions | faster-whisper `base` on CPU (model downloads on first use); never invented, no speech -> no captions |
| Render / export | FFmpeg via `video_editor/engine.py`: H.264 + AAC MP4, 720p/1080p, xfade transitions, loudnorm, ducked music |

The three styles differ in clip length, scoring weights, ordering (hook-first vs chronological), transition,
colour grade, loudness and audio treatment. There is no generative AI model; "AI" here means the analysis above.

The **edit decision list** (`doc.edl`, schema in `backend/schemas.py`) is the single source of truth: the
timeline shows it, the renderer consumes it, and it is saved with the project. Output positions come from one
layout function implemented in Python (`backend/services/layout.py`) and TypeScript (`frontend/src/lib/layout.ts`),
checked against each other by a shared fixture.

## Layout

```
backend/   api/ (routes) services/ (media, analysis, editing, rendering, pipeline) workers/ (jobs) tasks.py
frontend/  src/components/{layout,media,preview,timeline,ai-editor,export,panels}  hooks/  services/  lib/  store/
video_editor/   FFmpeg engine reused from the original Streamlit app (still runnable: streamlit run app.py)
```

## Tests

```bash
.venv/bin/python -m unittest -v tests.test_frameflow   # API end-to-end: real uploads, renders, export, captions (~90 s)
.venv/bin/python -m unittest -v tests.test_editor      # original engine tests
cd frontend && npm test && npm run typecheck           # layout parity + timeline edit logic
```

## Known limits

- Transcription needs `faster-whisper` and a one-time model download; otherwise the Captions control is disabled and says why.
- Preview of the timeline before rendering plays low-res proxies without transitions, grading or loudness
  (shown as "Draft"); click **Render preview** for the exact result.
- Smart crop uses face/motion heuristics, not object tracking. Zoom/pan keyframes, multi-track layering and
  stabilisation are not implemented.
- Single-user local app: no authentication.

---

# Original Streamlit editor (still available)

# AI Auto Video Editor

Local Streamlit app that edits video with FFmpeg from a **structured, validated plan**.

**My Projects** (`?page=projects`): searchable/sortable/filterable cards for editor projects (status Draft / In progress / Completed, real cover thumbnails, rename, duplicate, delete, details) and rendered videos (preview, download, share info, rename, delete). Reference: `design-reference/my-projects.png`.

**Streamlit app (`streamlit run app.py`): one unified workspace.** Top bar (project name, save status, undo/redo,
panel toggles, app menu → Dashboard / My Projects / Settings, Export) · narrow tool rail (Media, AI Edit, Audio, Text,
Captions, Effects, Templates) · left content panel · centre preview with playback controls · right AI panel
(Dynamic / Cinematic / Vlog / Shorts / Promotional, output format, five AI switches, advanced settings, Generate AI
Video; switches to Properties when a clip is selected) · full-width timeline (video / audio / captions / effects
tracks; select, split, trim, reorder, delete, zoom; drag its top edge to resize). Generate puts the edit **on the
timeline** for review; Export renders it (with Before/After). The React app (`./start.sh`) is the separate FrameFlow UI.

| Mode | How the plan is made |
|---|---|
| **Auto** | Goal text -> documented rules (platform -> aspect/loudness/captions, spoken footage -> pause removal) |
| **Custom** | You tick skills and tune settings from the capability registry |
| **Chat** | Natural-language requests revise the plan incrementally; unmet asks are reported |
| **Classic** | The original duration/aspect-ratio editor, unchanged |

Pipeline: upload -> plan (segments with source timestamps + skills + export) -> `validate` -> `engine` ->
preview / MP4 / plan JSON / EDL. Invalid plans never render.

## Capabilities

`video_editor/registry.py` is the single source of truth (id, name, category, description, inputs, settings,
dependencies, handler). A feature is shown as available only when its handler resolves **and** its dependencies
probe OK; everything else is listed with the missing dependency. See `docs/CAPABILITY_MAP.md` (regenerate with
`PYTHONPATH=. python scripts/gen_capability_map.py`).

Working now: trim/assemble, pause removal, best-moment selection (+hook), speed, resize (crop/blur/pad),
SRT/VTT captions, transitions, dialogue cleanup, loudness normalise, fades, music bed with ducking, colour
adjust/temperature/looks/LUT, denoise/sharpen/vignette/punch-in, titles, lower thirds, watermark, EDL export.

Not available (shown in the UI with the reason): auto-transcription (`pip install faster-whisper`), stabilisation
(FFmpeg built with libvidstab), beat sync (librosa), J/L-cuts, speed ramps, LLM planner (anthropic + API key),
and the external-tool items (AI masking, motion graphics, generative video, HDR grading, ...).

This FFmpeg build has no `subtitles`/`drawtext` filters, so captions and graphics are rendered with Pillow and
composited via `overlay`.

## Verify

```bash
python scripts/make_samples.py          # deterministic sample clips, no downloads
python -m unittest -v tests.test_editor # 23 end-to-end checks on real renders
```

---

## Original MVP notes

A local Streamlit app for combining multiple video clips into a single MP4,
with basic trimming to hit a target duration and a choice of aspect ratio.

**Classic tab:** deterministic, rule-based editor. It does
**not** use an AI model to understand your editing instructions yet -- the
text box is captured and saved next to each output for future reference, but
today's trimming logic is purely duration/aspect-ratio math. No paid APIs are
used.

## What it does

1. Upload one or more `.mp4` / `.mov` clips.
2. Optionally set a target total duration and pick an aspect ratio
   (16:9, 9:16, 1:1, 4:5, or match your first clip's own ratio).
3. The app trims each clip (evenly, from its center, to the target length)
   or uses it in full, scales/crops it to the chosen aspect ratio without
   distortion, and concatenates everything into one MP4.
4. Clips with no audio track get a silent track added automatically so
   concatenation works regardless of source audio.
5. Preview and download the result; every generated video is also saved in
   `outputs/` with a unique filename, plus a `.txt` sidecar recording the
   settings used.

## Requirements

- Python 3.9+
- [FFmpeg](https://ffmpeg.org/) (provides both `ffmpeg` and `ffprobe`) on your `PATH`
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - Windows: download from ffmpeg.org and add it to PATH

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
streamlit run app.py
```

Streamlit will open the app in your browser (default: http://localhost:8501).

## Project structure

```
app.py                   Streamlit UI
video_editor/
  ffmpeg_ops.py           ffprobe/ffmpeg subprocess wrappers
  planner.py              deterministic trim/aspect-ratio planning
  pipeline.py             orchestrates probe -> plan -> process -> concat
outputs/                  generated videos (gitignored, folder kept)
sample_videos/            optional local test clips (gitignored, folder kept)
```

## Known limitations (MVP)

- Editing instructions are saved but not interpreted -- no AI model is
  integrated yet.
- Trimming is center-based and duration-even across clips; there is no
  shot detection, highlight selection, or music sync.
- Re-encoding is used throughout (for consistent concatenation), so very
  large/long uploads will take noticeably longer to process.

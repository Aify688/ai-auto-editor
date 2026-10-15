import { create } from "zustand";
import { api } from "../services/api";
import type { Job, Media, NavKey, Project, ProjectDoc, RenderInfo, SystemStatus } from "../types";

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";
export type PreviewMode = "media" | "edit";

export interface Upload {
  id: string;
  name: string;
  progress: number;
  error: string | null;
}

interface Toast {
  id: number;
  kind: "info" | "error" | "success";
  text: string;
}

const HISTORY_LIMIT = 100;
const COALESCE_MS = 1200;
const LAST_PROJECT_KEY = "frameflow.lastProject";

export const lastProjectId = {
  get(): string | null {
    try {
      return localStorage.getItem(LAST_PROJECT_KEY);
    } catch {
      return null;
    }
  },
  set(id: string | null) {
    try {
      if (id) localStorage.setItem(LAST_PROJECT_KEY, id);
      else localStorage.removeItem(LAST_PROJECT_KEY);
    } catch {
      /* storage unavailable */
    }
  },
};

interface State {
  project: Omit<Project, "doc"> | null;
  doc: ProjectDoc | null;
  past: ProjectDoc[];
  future: ProjectDoc[];
  coalesce: { key: string; at: number } | null;
  saveState: SaveState;
  saveError: string | null;
  loadError: string | null;

  media: Media[];
  uploads: Upload[];
  jobs: Record<string, Job>; // latest job per kind ("generate", "render", "export", "transcribe")
  system: SystemStatus | null;

  nav: NavKey;
  selectedClipId: string | null;
  selectedMediaId: string | null;
  previewMode: PreviewMode;
  time: number;
  playing: boolean;
  seekNonce: number;
  toasts: Toast[];
  projectsOpen: boolean;
  exportOpen: boolean;

  openProject(id: string): Promise<void>;
  newProject(name?: string): Promise<void>;
  rename(name: string): void;
  updateDoc(recipe: (d: ProjectDoc) => ProjectDoc, opts?: { coalesce?: string; history?: boolean }): void;
  replaceEdlFromServer(doc: ProjectDoc): void;
  setRender(render: RenderInfo | null): void;
  undo(): void;
  redo(): void;
  markSaved(state: SaveState, error?: string | null): void;

  setMedia(media: Media[]): void;
  refreshMedia(): Promise<void>;
  setUploads(fn: (u: Upload[]) => Upload[]): void;
  setJob(job: Job): void;
  setSystem(s: SystemStatus): void;

  setNav(n: NavKey): void;
  selectClip(id: string | null): void;
  selectMedia(id: string | null): void;
  setPreviewMode(m: PreviewMode): void;
  setTime(t: number): void;
  seek(t: number): void;
  setPlaying(p: boolean): void;
  toast(text: string, kind?: Toast["kind"]): void;
  dismissToast(id: number): void;
  setProjectsOpen(o: boolean): void;
  setExportOpen(o: boolean): void;
}

let toastSeq = 0;

export const useStore = create<State>((set, get) => ({
  project: null,
  doc: null,
  past: [],
  future: [],
  coalesce: null,
  saveState: "idle",
  saveError: null,
  loadError: null,
  media: [],
  uploads: [],
  jobs: {},
  system: null,
  nav: "media",
  selectedClipId: null,
  selectedMediaId: null,
  previewMode: "media",
  time: 0,
  playing: false,
  seekNonce: 0,
  toasts: [],
  projectsOpen: false,
  exportOpen: false,

  async openProject(id) {
    const [p, media, jobs] = await Promise.all([api.getProject(id), api.listMedia(id), api.projectJobs(id)]);
    const { doc, ...meta } = p;
    const latest: Record<string, Job> = {};
    for (const j of jobs) if (j.kind !== "ingest" && !latest[j.kind]) latest[j.kind] = j;
    set({
      project: meta,
      doc,
      past: [],
      future: [],
      coalesce: null,
      saveState: "saved",
      saveError: null,
      loadError: null,
      media,
      uploads: [],
      jobs: latest,
      selectedClipId: null,
      selectedMediaId: media.find((m) => m.kind !== "audio")?.id ?? null,
      previewMode: doc.edl?.clips.length ? "edit" : "media",
      time: 0,
      playing: false,
    });
    lastProjectId.set(id);
  },

  async newProject(name = "Untitled project") {
    const p = await api.createProject(name);
    await get().openProject(p.id);
  },

  rename(name) {
    const p = get().project;
    if (!p || !name.trim() || name === p.name) return;
    set({ project: { ...p, name: name.trim() }, saveState: "dirty" });
  },

  updateDoc(recipe, opts = {}) {
    const { doc, past, coalesce } = get();
    if (!doc) return;
    const next = recipe(doc);
    if (next === doc) return;
    const now = Date.now();
    // "drag:*" keys are unique per pointer gesture, so a whole drag is one undo step however long it takes.
    const merge =
      !!opts.coalesce && coalesce?.key === opts.coalesce && (opts.coalesce.startsWith("drag:") || now - coalesce.at < COALESCE_MS);
    const record = opts.history !== false && !merge;
    set({
      doc: next,
      past: record ? [...past, doc].slice(-HISTORY_LIMIT) : past,
      future: opts.history === false ? get().future : [],
      coalesce: opts.coalesce ? { key: opts.coalesce, at: now } : null,
      saveState: "dirty",
    });
  },

  replaceEdlFromServer(serverDoc) {
    // A finished job produced a new EDL: adopt it as an undoable step.
    get().updateDoc((d) => ({ ...d, edl: serverDoc.edl }));
  },

  setRender(render) {
    const p = get().project;
    if (p) set({ project: { ...p, render } });
  },

  undo() {
    const { past, doc, future } = get();
    if (!past.length || !doc) return;
    set({ doc: past[past.length - 1], past: past.slice(0, -1), future: [doc, ...future], saveState: "dirty", coalesce: null });
  },

  redo() {
    const { past, doc, future } = get();
    if (!future.length || !doc) return;
    set({ doc: future[0], past: [...past, doc], future: future.slice(1), saveState: "dirty", coalesce: null });
  },

  markSaved(state, error = null) {
    set({ saveState: state, saveError: error });
  },

  setMedia(media) {
    set({ media });
  },

  async refreshMedia() {
    const p = get().project;
    if (p) set({ media: await api.listMedia(p.id) });
  },

  setUploads(fn) {
    set({ uploads: fn(get().uploads) });
  },

  setJob(job) {
    set({ jobs: { ...get().jobs, [job.kind]: job } });
  },

  setSystem(system) {
    set({ system });
  },

  setNav(nav) {
    set({ nav });
  },
  selectClip(selectedClipId) {
    set({ selectedClipId });
  },
  selectMedia(selectedMediaId) {
    set({ selectedMediaId, previewMode: selectedMediaId ? "media" : get().previewMode, playing: false });
  },
  setPreviewMode(previewMode) {
    set({ previewMode, playing: false });
  },
  setTime(time) {
    set({ time });
  },
  seek(time) {
    set({ time: Math.max(0, time), seekNonce: get().seekNonce + 1 });
  },
  setPlaying(playing) {
    set({ playing });
  },
  toast(text, kind = "info") {
    const id = ++toastSeq;
    set({ toasts: [...get().toasts, { id, kind, text }] });
    setTimeout(() => get().dismissToast(id), kind === "error" ? 7000 : 3500);
  },
  dismissToast(id) {
    set({ toasts: get().toasts.filter((t) => t.id !== id) });
  },
  setProjectsOpen(projectsOpen) {
    set({ projectsOpen });
  },
  setExportOpen(exportOpen) {
    set({ exportOpen });
  },
}));

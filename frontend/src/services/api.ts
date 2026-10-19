import type { AnimateOptions, ImageToVideoStatus } from "../types/animate";
import type { Preferences, TtsStatus } from "../types/tts";
import type { GenerationPlan, InstructionPlan, Job, Media, MusicLibraryTrack, MusicRecommendations, Project, ProjectDoc, ProjectSummary, SystemStatus, TemplateDef } from "../types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError("Cannot reach the FrameFlow server. Is the backend running on port 8000?", 0);
  }
  const type = res.headers.get("content-type") ?? "";
  const isJson = /\bjson\b/i.test(type);
  if (!res.ok) {
    let detail = res.statusText || `Request failed (${res.status})`;
    if (isJson) {
      try {
        const body = await res.json();
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
      } catch {
        /* unreadable error body: keep the status text */
      }
    } else if (/html/i.test(type)) {
      detail = STALE_HINT;
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  // Never hand an HTML page to the JSON parser: that is what produced "Unexpected token '<'".
  if (!isJson) throw new ApiError(/html/i.test(type) ? STALE_HINT : `The server sent an unexpected response (${type || "no content type"}).`, res.status);
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError("The server sent data the app could not read. Try again.", res.status);
  }
}

/** The server answered an API request with the web page: it is an older version that does not know this endpoint. */
const STALE_HINT = "The FrameFlow server did not recognise this request. It is probably running an older version: restart it with ./start.sh --restart, then reload this page.";

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  system: () => request<SystemStatus>("/api/system"),
  musicLibrary: () => request<MusicLibraryTrack[]>("/api/system/music-library"),
  previewPlan: (instruction: string) => request<InstructionPlan>("/api/projects/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instruction }) }),
  preferences: () => request<Preferences>("/api/system/preferences"),
  setPreferences: (patch: { whisperModel?: string }) => request<Preferences>("/api/system/preferences", { method: "PUT", body: json(patch) }),
  ttsVoices: () => request<TtsStatus>("/api/system/tts-voices"),
  tts: (pid: string, body: { text: string; voice: string; rate: number }) =>
    request<Media>(`/api/projects/${pid}/tts`, { method: "POST", body: json(body) }),
  fonts: () => request<{ family: string; bold: boolean }[]>("/api/system/fonts"),
  templates: () => request<TemplateDef[]>("/api/templates"),
  musicRecommendations: (pid: string) => request<MusicRecommendations>(`/api/projects/${pid}/music-recommendations`),

  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", { method: "POST", body: json({ name }) }),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  updateProject: (id: string, patch: { name?: string; doc?: ProjectDoc }) =>
    request<Project>(`/api/projects/${id}`, { method: "PUT", body: json(patch) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  restoreVersion: (pid: string, versionId: string) =>
    request<Project>(`/api/projects/${pid}/render/restore`, { method: "POST", body: json({ id: versionId }) }),

  listMedia: (pid: string) => request<Media[]>(`/api/projects/${pid}/media`),
  deleteMedia: (id: string) => request<void>(`/api/media/${id}`, { method: "DELETE" }),
  retryMedia: (id: string) => request<Media>(`/api/media/${id}/retry`, { method: "POST" }),
  reorderMedia: (pid: string, ids: string[]) =>
    request<Media[]>(`/api/projects/${pid}/media/order`, { method: "PUT", body: json({ ids }) }),
  peaks: (url: string) => request<number[]>(url),

  imageToVideo: () => request<ImageToVideoStatus>("/api/system/image-to-video"),
  animate: (pid: string, body: AnimateOptions) => request<Job>(`/api/projects/${pid}/animate`, { method: "POST", body: json(body) }),
  generate: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/generate`, { method: "POST", body: json({ doc }) }),
  generationPlan: (pid: string, doc: ProjectDoc) =>
    request<GenerationPlan>(`/api/projects/${pid}/generation/plan`, { method: "POST", body: json({ doc }) }),
  renderPreview: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/render`, { method: "POST", body: json({ doc }) }),
  exportVideo: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/export`, { method: "POST", body: json({ doc }) }),
  transcribe: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/transcribe`, { method: "POST", body: json({ doc }) }),
  projectJobs: (pid: string) => request<Job[]>(`/api/projects/${pid}/jobs`),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  startMatte: (mediaId: string, force = false) => request<Job>(`/api/media/${mediaId}/matte?force=${force}`, { method: "POST" }),
  matteStatus: (mediaId: string) => request<{ ready: boolean; ok: boolean; modelCached: boolean; hint: string | null }>(`/api/media/${mediaId}/matte`),
  bgPreview: async (mediaId: string, body: { t: number; mode: string; color: string; blur: number; bgMediaId: string | null }) => {
    const r = await fetch(`/api/media/${mediaId}/bgpreview`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(((await r.json().catch(() => null)) as { detail?: string } | null)?.detail ?? `Preview failed (${r.status})`);
    return URL.createObjectURL(await r.blob());
  },
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  retryJob: (id: string) => request<Job>(`/api/jobs/${id}/retry`, { method: "POST" }),
  revealJob: (id: string) => request<{ ok: boolean }>(`/api/jobs/${id}/reveal`, { method: "POST" }),
  downloadUrl: (id: string) => `/api/jobs/${id}/download`,

  /** Upload with real byte progress (fetch has no upload progress events). */
  upload(pid: string, file: File, onProgress: (fraction: number) => void): Promise<Media> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `/api/projects/${pid}/media`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
      xhr.onload = () => {
        let body: any = null;
        try {
          body = JSON.parse(xhr.responseText);
        } catch {
          /* ignore */
        }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as Media);
        else reject(new ApiError(body?.detail ?? `Upload failed (${xhr.status})`, xhr.status));
      };
      xhr.onerror = () => reject(new ApiError("Upload failed: server unreachable.", 0));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
};

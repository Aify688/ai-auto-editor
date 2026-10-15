import type { Job, Media, Project, ProjectDoc, ProjectSummary, SystemStatus } from "../types";

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
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown) => JSON.stringify(body);

export const api = {
  system: () => request<SystemStatus>("/api/system"),

  listProjects: () => request<ProjectSummary[]>("/api/projects"),
  createProject: (name: string) => request<Project>("/api/projects", { method: "POST", body: json({ name }) }),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  updateProject: (id: string, patch: { name?: string; doc?: ProjectDoc }) =>
    request<Project>(`/api/projects/${id}`, { method: "PUT", body: json(patch) }),
  deleteProject: (id: string) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),

  listMedia: (pid: string) => request<Media[]>(`/api/projects/${pid}/media`),
  deleteMedia: (id: string) => request<void>(`/api/media/${id}`, { method: "DELETE" }),
  retryMedia: (id: string) => request<Media>(`/api/media/${id}/retry`, { method: "POST" }),
  reorderMedia: (pid: string, ids: string[]) =>
    request<Media[]>(`/api/projects/${pid}/media/order`, { method: "PUT", body: json({ ids }) }),
  peaks: (url: string) => request<number[]>(url),

  generate: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/generate`, { method: "POST", body: json({ doc }) }),
  renderPreview: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/render`, { method: "POST", body: json({ doc }) }),
  exportVideo: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/export`, { method: "POST", body: json({ doc }) }),
  transcribe: (pid: string, doc: ProjectDoc) =>
    request<Job>(`/api/projects/${pid}/transcribe`, { method: "POST", body: json({ doc }) }),
  projectJobs: (pid: string) => request<Job[]>(`/api/projects/${pid}/jobs`),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
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

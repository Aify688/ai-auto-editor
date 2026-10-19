import { useEffect } from "react";
import { api } from "../services/api";
import { useStore } from "../store/project";
import type { Job, ProjectDoc } from "../types";

type Kind = "generate" | "render" | "export" | "transcribe";

const starters: Record<Kind, (pid: string, doc: ProjectDoc) => Promise<Job>> = {
  generate: api.generate,
  render: api.renderPreview,
  export: api.exportVideo,
  transcribe: api.transcribe,
};

export const isActive = (job?: Job | null) => !!job && (job.status === "queued" || job.status === "running");

let autoEditStarting = false;

/** One-click footage editing: cut pauses and filler words, caption the speech, and add background music that ducks
 *  under dialogue. Running it again rebuilds the whole edit (captions and music included), so nothing piles up, and the
 *  result is one undo step. */
export async function startAutoEdit(): Promise<Job | null> {
  const { doc, jobs } = useStore.getState();
  if (!doc || autoEditStarting || isActive(jobs.generate)) return null;   // no duplicate requests
  autoEditStarting = true;
  try {
    return await runAutoEdit(doc);
  } finally {
    autoEditStarting = false;
  }
}

function runAutoEdit(doc: ProjectDoc) {
  return startJob("generate", {
    ...doc,
    settings: {
      ...doc.settings,
      captions: true,
      burnCaptions: true,
      sceneDetection: true,
      highlightDetection: true,
      removeSilence: true,
      removeFillers: true,
      musicSource: doc.settings.musicSource === "none" ? "auto" : doc.settings.musicSource,
    },
  });
}

/** Start a backend job for the current project using the current document. */
export async function startJob(kind: Kind, docOverride?: ProjectDoc): Promise<Job | null> {
  const { project, doc, setJob, toast } = useStore.getState();
  if (!project || !doc) return null;
  try {
    const job = await starters[kind](project.id, docOverride ?? doc);
    setJob(job);
    return job;
  } catch (e) {
    toast((e as Error).message, "error");
    return null;
  }
}

export async function cancelJob(job: Job) {
  try {
    useStore.getState().setJob(await api.cancelJob(job.id));
  } catch (e) {
    useStore.getState().toast((e as Error).message, "error");
  }
}

export async function retryJob(job: Job) {
  try {
    useStore.getState().setJob(await api.retryJob(job.id));
  } catch (e) {
    useStore.getState().toast((e as Error).message, "error");
  }
}

function onFinished(job: Job) {
  const s = useStore.getState();
  if (job.status === "failed") {
    if (job.kind !== "export") s.toast(job.error ?? "Job failed", "error");
    return;
  }
  if (job.status !== "done" || !job.result) return;
  if (job.kind === "generate" || job.kind === "textvideo") {
    const applied = job.result.appliedDoc as { style: ProjectDoc["style"]; aspect: ProjectDoc["aspect"]; template: string | null; settings: ProjectDoc["settings"] } | undefined;
    // One history entry: undo returns to the settings and timeline from before the AI's plan was applied.
    s.updateDoc((d) => ({
      ...d,
      ...(applied ? { style: applied.style, aspect: applied.aspect, template: applied.template, settings: { ...applied.settings, instruction: d.settings.instruction } } : {}),
      edl: job.result!.edl,
    }));
    s.setRender(job.result.render);
    s.selectClip(null);
    s.setPreviewMode("edit");
    s.seek(0);
    if (job.kind === "textvideo") void s.refreshMedia();     // the generated scenes are now library media
    s.toast(job.kind === "textvideo" ? "AI video ready" : "AI edit ready", "success");
  } else if (job.kind === "render") {
    s.setRender(job.result.render);
    s.setPreviewMode("edit");
    s.toast("Preview updated", "success");
  } else if (job.kind === "animate") {
    void s.refreshMedia();                                  // the animation is now in the media library
    s.toast("Animation ready", "success");
  } else if (job.kind === "matte") {
    s.toast("Subject found. Render a preview to see the new background.", "success");
  } else if (job.kind === "transcribe") {
    const captions = job.result.captions ?? [];
    s.updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, captions } } : d));
    s.toast(captions.length ? `${captions.length} captions created` : (job.result.notes?.[0] ?? "No speech detected"),
      captions.length ? "success" : "info");
  }
}

/** Poll running jobs and apply their results when they finish. */
export function useJobPoller() {
  const projectId = useStore((s) => s.project?.id);
  useEffect(() => {
    if (!projectId) return;
    let stopped = false;
    const tick = async () => {
      const { jobs, setJob } = useStore.getState();
      const running = Object.values(jobs).filter((j) => isActive(j) && j.projectId === projectId);
      await Promise.all(
        running.map(async (j) => {
          try {
            const next = await api.job(j.id);
            if (stopped || useStore.getState().project?.id !== projectId) return;
            setJob(next);
            if (!isActive(next)) onFinished(next);
          } catch {
            /* transient network error: try again next tick */
          }
        }),
      );
      if (!stopped) timer = window.setTimeout(tick, running.length ? 500 : 1000);
    };
    let timer = window.setTimeout(tick, 300);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [projectId]);
}

/** Refresh the media list while anything is still being processed. */
export function useMediaPoller() {
  const projectId = useStore((s) => s.project?.id);
  const processing = useStore((s) => s.media.some((m) => m.status === "processing"));
  useEffect(() => {
    if (!projectId || !processing) return;
    const id = window.setInterval(() => {
      useStore.getState().refreshMedia().catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(id);
  }, [projectId, processing]);
}

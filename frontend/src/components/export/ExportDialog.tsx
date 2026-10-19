import { AlertTriangle, CheckCircle2, Download, FolderOpen, Loader2, RotateCw, X } from "lucide-react";
import { useMemo, useState } from "react";
import { cancelJob, isActive, retryJob, startJob } from "../../hooks/useJobs";
import { aspectDims, fmtBytes, fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { QUALITY, estimateBytes } from "../../lib/styles";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { ExportSettings } from "../../types";
import { Button, Field, Modal, Segmented, Select } from "../ui/controls";

export function ExportDialog() {
  const open = useStore((s) => s.exportOpen);
  const setOpen = useStore((s) => s.setExportOpen);
  const doc = useStore((s) => s.doc);
  const job = useStore((s) => s.jobs.export);
  const updateDoc = useStore((s) => s.updateDoc);
  const duration = useMemo(() => (doc?.edl ? layout(doc.edl).duration : 0), [doc?.edl]);
  const [dismissed, setDismissed] = useState<string | null>(null);
  if (!doc) return null;
  const ex = doc.export;
  const aspect = doc.edl?.aspect ?? doc.aspect;
  const [w, h] = aspectDims(aspect, ex.resolution);
  const running = isActive(job);
  const done = job?.status === "done" && job.result && job.id !== dismissed;
  const set = (patch: Partial<ExportSettings>, coalesce?: string) =>
    updateDoc((d) => ({ ...d, export: { ...d.export, ...patch } }), { coalesce, history: false });

  const start = () => {
    if (!ex.filename.trim()) return;
    startJob("export");
  };

  return (
    <Modal open={open} onClose={() => setOpen(false)} title="Export video" width={440} dismissable={!running}>
      <div className="space-y-1 px-4 py-3">
        {done ? (
          <div className="py-2 text-center">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-success/15"><CheckCircle2 size={30} className="text-success" /></div>
            <div className="mt-2 text-base font-semibold text-fg">Export complete</div>
            <div className="mt-1 text-xs text-fg-muted">{job!.result!.filename}</div>
            <div className="mt-0.5 text-xs tabular-nums text-fg-faint">
              {job!.result!.width}×{job!.result!.height} · {Math.round(job!.result!.fps)} fps · {fmtDuration(job!.result!.duration)} · {fmtBytes(job!.result!.size)}
            </div>
            {(job!.result!.warnings ?? []).map((w: string) => (
              <div key={w} className="mt-1 text-2xs text-warn">{w}</div>
            ))}
            {job!.result!.subtitlesFile && (
              <div className="mt-1 text-2xs text-fg-muted">Subtitles saved alongside the video as {job!.result!.subtitlesFile}</div>
            )}
            <div className="mt-4 flex justify-center gap-2">
              <a href={api.downloadUrl(job!.id)} download className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-primary-ink hover:bg-primary-hover">
                <Download size={14} /> Download MP4
              </a>
              <Button
                icon={<FolderOpen size={14} />}
                onClick={() => api.revealJob(job!.id).catch((e) => useStore.getState().toast(e.message, "error"))}
              >
                Show in folder
              </Button>
            </div>
            <video src={job!.result!.url} controls className="mx-auto mt-4 max-h-56 rounded-xl border border-line bg-black" />
            <button onClick={() => setDismissed(job!.id)} className="mt-3 text-xs text-fg-muted hover:text-fg">
              Export again with other settings
            </button>
          </div>
        ) : (
          <>
            <Field label="File name">
              <div className="flex items-center gap-1">
                <input
                  value={ex.filename}
                  maxLength={100}
                  disabled={running}
                  aria-label="File name"
                  onChange={(e) => set({ filename: e.target.value }, "fname")}
                  className="h-8 w-48 rounded-lg border border-line bg-app px-2 text-xs text-fg outline-none focus:border-primary"
                />
                <span className="text-xs text-fg-faint">.mp4</span>
              </div>
            </Field>
            <Field label="Resolution" hint={aspect === "original" ? "Matches the source clip's own aspect ratio" : `${w} × ${h} (${aspect})`}>
              <div className="w-48">
                <Segmented label="Resolution" value={ex.resolution} onChange={(v) => set({ resolution: v })}
                  options={[{ value: 720, label: "720p" }, { value: 1080, label: "1080p" }, { value: 2160, label: "4K" }]} />
              </div>
            </Field>
            <Field label="Format">
              <span className="text-xs text-fg-muted">MP4 · H.264 / AAC</span>
            </Field>
            <Field label="Frame rate">
              <Select label="Frame rate" className="w-36" value={ex.fps} onChange={(v) => set({ fps: v })}
                options={[24, 30, 60].map((f) => ({ value: f as ExportSettings["fps"], label: `${f} fps` }))} />
            </Field>
            <Field label="Subtitles" hint={!doc.edl?.captions.length ? "No captions on the timeline" : undefined}>
              <Segmented label="Subtitles" value={ex.subtitleHandling} onChange={(v) => set({ subtitleHandling: v })}
                options={[{ value: "burn", label: "Burn in" }, { value: "srt", label: "SRT file" }, { value: "none", label: "None" }]} />
            </Field>
            <Field label="Quality" hint={`${QUALITY[ex.quality][ex.resolution] * (ex.fps > 30 ? 1.5 : 1) / 1000} Mbps video`}>
              <div className="w-48">
                <Segmented label="Quality" value={ex.quality} onChange={(v) => set({ quality: v })}
                  options={(["draft", "standard", "high"] as const).map((q) => ({ value: q, label: QUALITY[q].label }))} />
              </div>
            </Field>
            <Field label="Estimated size" hint={`${fmtDuration(duration)} at target bitrate`}>
              <span className="text-xs tabular-nums text-fg">≈ {fmtBytes(estimateBytes(duration, ex.quality, ex.resolution, ex.fps))}</span>
            </Field>

            {running && job && (
              <div className="mt-2 rounded-xl border border-line bg-panel2 p-3">
                <div className="mb-1.5 flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1.5 text-fg"><Loader2 size={12} className="animate-spin text-primary" /> {job.message}</span>
                  <span className="tabular-nums text-fg-muted">{Math.round(job.progress * 100)}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-line"><div className="h-full bg-primary transition-[width] duration-300" style={{ width: `${job.progress * 100}%` }} /></div>
              </div>
            )}
            {job?.status === "failed" && job.id !== dismissed && (
              <div className="mt-2 flex gap-2 rounded-xl border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" /> <span className="break-words">{job.error}</span>
              </div>
            )}
          </>
        )}
      </div>
      {!done && (
        <div className="flex justify-end gap-2 border-t border-line px-4 py-3">
          {running && job ? (
            <Button icon={<X size={14} />} onClick={() => cancelJob(job)}>Cancel export</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={() => setOpen(false)}>Close</Button>
              {job?.status === "failed" && <Button icon={<RotateCw size={14} />} onClick={() => retryJob(job)}>Retry</Button>}
              <Button variant="primary" onClick={start} disabled={!doc.edl?.clips.length || !ex.filename.trim()}>Export</Button>
            </>
          )}
        </div>
      )}
    </Modal>
  );
}

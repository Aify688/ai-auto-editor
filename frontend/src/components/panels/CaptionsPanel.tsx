import { Captions, Loader2, Mic, Trash2, X } from "lucide-react";
import { useMemo } from "react";
import { cancelJob, isActive, startJob } from "../../hooks/useJobs";
import { fmtTime } from "../../lib/format";
import { captionSpans, layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import { Button, Empty, Field, PanelHeader, Toggle } from "../ui/controls";
import { editEdl } from "./shared";

export function CaptionsPanel() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const job = useStore((s) => s.jobs.transcribe);
  const sys = useStore((s) => s.system?.transcription);
  const spans = useMemo(() => (edl ? captionSpans(edl.captions, layout(edl).clips) : []), [edl]);
  const running = isActive(job);

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Captions" subtitle="Speech-to-text, edited by you." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {!edl || !edl.clips.length ? (
          <Empty icon={<Captions size={18} />} title="No timeline yet" text="Generate an edit, then create captions from its speech." />
        ) : (
          <>
            <div className="rounded-md bg-panel2 p-2.5">
              {running && job ? (
                <div>
                  <div className="mb-1.5 flex items-center justify-between text-xs text-fg">
                    <span className="flex items-center gap-1.5"><Loader2 size={12} className="animate-spin text-primary" /> {job.message}</span>
                    <span className="tabular-nums text-fg-muted">{Math.round(job.progress * 100)}%</span>
                  </div>
                  <div className="h-1 overflow-hidden rounded bg-line"><div className="h-full bg-primary transition-[width]" style={{ width: `${job.progress * 100}%` }} /></div>
                  <Button size="sm" variant="ghost" className="mt-1.5 w-full" icon={<X size={12} />} onClick={() => cancelJob(job)}>Cancel</Button>
                </div>
              ) : (
                <>
                  <Button variant="primary" size="sm" className="w-full" icon={<Mic size={13} />} disabled={!sys?.ok} onClick={() => startJob("transcribe")}>
                    {edl.captions.length ? "Re-transcribe speech" : "Generate captions"}
                  </Button>
                  <p className="mt-1.5 text-2xs text-fg-faint">
                    {sys?.ok ? `${sys.engine}${sys.modelCached ? "" : " · model downloads on first use"}` : `Unavailable: ${sys?.hint ?? "speech-to-text not installed"}`}
                  </p>
                  {job?.status === "failed" && <p className="mt-1 text-2xs text-danger">{job.error}</p>}
                </>
              )}
            </div>
            <Field label="Burn into video" hint="Off keeps captions out of the export">
              <Toggle label="Burn captions into video" checked={edl.burnCaptions} onChange={(v) => editEdl((e) => ({ ...e, burnCaptions: v }))} />
            </Field>
            <div className="mt-2 space-y-1.5">
              {spans.length === 0 ? (
                <p className="py-4 text-center text-2xs text-fg-faint">
                  {edl.captions.length ? "No captions fall inside the current clips." : "No captions yet."}
                </p>
              ) : (
                spans.map((s, i) => (
                  <div key={`${s.caption.id}-${i}`} className="group rounded border border-line bg-panel2 p-1.5">
                    <div className="mb-1 flex items-center justify-between">
                      <button onClick={() => { useStore.getState().setPreviewMode("edit"); useStore.getState().seek(s.outStart); }} className="text-2xs tabular-nums text-primary hover:underline">
                        {fmtTime(s.outStart, true)} – {fmtTime(s.outEnd, true)}
                      </button>
                      <button aria-label="Delete caption" onClick={() => editEdl((e) => ({ ...e, captions: e.captions.filter((c) => c.id !== s.caption.id) }))} className="text-fg-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100">
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <textarea
                      value={s.caption.text}
                      aria-label="Caption text"
                      rows={Math.min(3, Math.ceil(s.caption.text.length / 34) || 1)}
                      onChange={(e) => {
                        const text = e.target.value;
                        editEdl((x) => ({ ...x, captions: x.captions.map((c) => (c.id === s.caption.id ? { ...c, text } : c)) }), `cap-${s.caption.id}`);
                      }}
                      className="w-full resize-none rounded border border-transparent bg-transparent px-1 text-xs text-fg outline-none focus:border-primary focus:bg-panel"
                    />
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

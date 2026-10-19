import { Captions, Download, Loader2, Mic, Trash2, Type, X } from "lucide-react";
import { useMemo } from "react";
import { cancelJob, isActive, startJob } from "../../hooks/useJobs";
import { fmtTime } from "../../lib/format";
import { captionSpans, layout } from "../../lib/layout";
import { resetCaption, retimeCaption } from "../../lib/timelineOps";
import { useStore } from "../../store/project";
import { CAPTION_PRESETS, DEFAULT_CAPTION_STYLE, SUBTITLE_LANGUAGES, retimeWords } from "../../lib/styles";
import type { CaptionAnimation, CaptionBackground, CaptionFontSize, CaptionPosition, CaptionStyle } from "../../types";
import { Button, Empty, Field, PanelHeader, Segmented, Select, Toggle, cx } from "../ui/controls";
import { editEdl } from "./shared";

const FONT_SIZES: { value: CaptionFontSize; label: string }[] = [
  { value: "small", label: "S" },
  { value: "medium", label: "M" },
  { value: "large", label: "L" },
];

const POSITIONS: { value: CaptionPosition; label: string }[] = [
  { value: "top", label: "Top" },
  { value: "center", label: "Mid" },
  { value: "bottom", label: "Bot" },
];

const BACKGROUNDS: { value: CaptionBackground; label: string }[] = [
  { value: "box", label: "Box" },
  { value: "outline", label: "Outline" },
  { value: "none", label: "None" },
];

const DEFAULT_STYLE: CaptionStyle = DEFAULT_CAPTION_STYLE;

const ANIMATIONS: { value: CaptionAnimation; label: string }[] = [
  { value: "none", label: "None" },
  { value: "fade", label: "Fade" },
  { value: "pop", label: "Pop" },
  { value: "scale", label: "Scale" },
];

function patchStyle(patch: Partial<CaptionStyle>) {
  editEdl((e) => ({
    ...e,
    captionStyle: { ...(e.captionStyle ?? DEFAULT_STYLE), preset: "custom", ...patch },
  }));
}

function applyPreset(style: CaptionStyle) {
  editEdl((e) => ({ ...e, captionStyle: { ...(e.captionStyle ?? DEFAULT_STYLE), ...style } }));
}

/** Move a caption edge by the amount the user typed (timeline time maps 1:1 to source time). The transcript is kept. */
function moveEdge(id: string, edge: "start" | "end", delta: number) {
  editEdl((e) => ({
    ...e,
    captions: e.captions.map((c) => (c.id !== id ? c : edge === "start" ? retimeCaption(c, Math.min(delta, c.srcEnd - c.srcStart - 0.2), 0) : retimeCaption(c, 0, Math.max(delta, -(c.srcEnd - c.srcStart) + 0.2)))),
  }), `capt-${id}-${edge}`);
}

function TimeInput({ label, value, onCommit }: { label: string; value: number; onCommit: (v: number) => void }) {
  return (
    <input
      aria-label={label}
      key={value}
      defaultValue={value.toFixed(2)}
      inputMode="decimal"
      onBlur={(e) => { const v = parseFloat(e.target.value); if (Number.isFinite(v) && Math.abs(v - value) > 0.004) onCommit(v - value); else e.target.value = value.toFixed(2); }}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className="h-6 w-16 rounded border border-line bg-app px-1 text-right text-2xs tabular-nums text-fg outline-none focus:border-primary"
    />
  );
}

function downloadCaptions(projectId: string, fmt: "srt" | "vtt") {
  const a = document.createElement("a");
  a.href = `/api/projects/${projectId}/captions.${fmt}`;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function CaptionsPanel() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const project = useStore((s) => s.project);
  const job = useStore((s) => s.jobs.transcribe);
  const sys = useStore((s) => s.system?.transcription);
  const spans = useMemo(() => (edl ? captionSpans(edl.captions, layout(edl).clips) : []), [edl]);
  const running = isActive(job);
  const style = edl?.captionStyle ?? DEFAULT_STYLE;
  const hasCaptions = spans.length > 0;
  const selectedCaption = useStore((s) => s.selectedCaptionId);
  const language = useStore((s) => s.doc?.settings.subtitleLanguage ?? "auto");
  const updateDoc = useStore((s) => s.updateDoc);
  const hasWords = !!edl?.captions.some((c) => c.words && c.words.length);

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Captions" subtitle="Speech-to-text, styled your way." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {!edl || !edl.clips.length ? (
          <Empty icon={<Captions size={18} />} title="No timeline yet" text="Generate an edit, then create captions from its speech." />
        ) : (
          <>
            {/* ── Transcribe ────────────────────────────────── */}
            <div className="rounded-xl border border-line bg-panel2 p-3">
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
                  <Field label="Language" hint="Speech language">
                    <Select
                      label="Caption language"
                      className="w-36"
                      value={language}
                      options={SUBTITLE_LANGUAGES}
                      onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, subtitleLanguage: v } }))}
                    />
                  </Field>
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

            {/* ── Burn toggle ───────────────────────────────── */}
            <Field label="Burn into video" hint="Off keeps captions out of the export">
              <Toggle label="Burn captions into video" checked={edl.burnCaptions} onChange={(v) => editEdl((e) => ({ ...e, burnCaptions: v }))} />
            </Field>

            {/* ── Caption Style ─────────────────────────────── */}
            {edl.captions.length > 0 && (
              <section className="mt-3 space-y-2 rounded-xl border border-line bg-panel2 px-3 py-3">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">
                  <Type size={12} /> Style
                </h3>

                <div className="grid grid-cols-5 gap-1" role="radiogroup" aria-label="Caption preset">
                  {CAPTION_PRESETS.map((p) => (
                    <button
                      key={p.value}
                      role="radio"
                      aria-checked={style.preset === p.value}
                      onClick={() => applyPreset(p.style)}
                      className={cx("rounded-lg border px-1 py-1.5 text-2xs font-medium transition-colors",
                        style.preset === p.value ? "border-primary bg-primary-muted text-primary" : "border-line bg-panel text-fg-muted hover:text-fg")}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>

                <Field label="Font size">
                  <Segmented<CaptionFontSize>
                    label="Font size"
                    value={style.fontSize}
                    options={FONT_SIZES}
                    onChange={(v) => patchStyle({ fontSize: v })}
                  />
                </Field>

                <Field label="Position">
                  <Segmented<CaptionPosition>
                    label="Caption position"
                    value={style.position}
                    options={POSITIONS}
                    onChange={(v) => patchStyle({ position: v })}
                  />
                </Field>

                <Field label="Background">
                  <Segmented<CaptionBackground>
                    label="Background style"
                    value={style.background}
                    options={BACKGROUNDS}
                    onChange={(v) => patchStyle({ background: v })}
                  />
                </Field>

                <Field label="Text colour">
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      aria-label="Text colour"
                      value={style.color}
                      onChange={(e) => patchStyle({ color: e.target.value })}
                      className="h-7 w-10 cursor-pointer rounded border border-line bg-transparent"
                    />
                    <span className="text-2xs tabular-nums text-fg-muted">{style.color}</span>
                  </div>
                </Field>

                <Field label="Highlight colour" hint="For word-level emphasis">
                  <div className="flex items-center gap-2">
                    <input
                      type="color"
                      aria-label="Highlight colour"
                      value={style.highlightColor}
                      onChange={(e) => patchStyle({ highlightColor: e.target.value })}
                      className="h-7 w-10 cursor-pointer rounded border border-line bg-transparent"
                    />
                    <span className="text-2xs tabular-nums text-fg-muted">{style.highlightColor}</span>
                  </div>
                </Field>

                <Field label="Animation">
                  <Segmented<CaptionAnimation>
                    label="Caption animation"
                    value={style.animation ?? "none"}
                    options={ANIMATIONS}
                    onChange={(v) => patchStyle({ animation: v })}
                  />
                </Field>

                <Field label="Karaoke highlight" hint={hasWords ? "Word by word" : "Needs word timing: re-transcribe"}>
                  <Toggle label="Karaoke highlight" checked={!!style.karaoke} disabled={!hasWords} onChange={(v) => patchStyle({ karaoke: v })} />
                </Field>

                <Field label="Uppercase">
                  <Toggle label="All caps" checked={style.uppercase} onChange={(v) => patchStyle({ uppercase: v })} />
                </Field>
              </section>
            )}

            {/* ── Export subtitles ──────────────────────────── */}
            {hasCaptions && project && (
              <div className="mt-3 flex gap-2">
                <Button size="sm" className="flex-1" icon={<Download size={12} />} onClick={() => downloadCaptions(project.id, "srt")}>
                  SRT
                </Button>
                <Button size="sm" className="flex-1" icon={<Download size={12} />} onClick={() => downloadCaptions(project.id, "vtt")}>
                  VTT
                </Button>
              </div>
            )}

            {/* ── Caption list ──────────────────────────────── */}
            <div className="mt-3 space-y-1.5">
              {spans.length === 0 ? (
                <p className="py-4 text-center text-2xs text-fg-faint">
                  {edl.captions.length ? "No captions fall inside the current clips." : "No captions yet."}
                </p>
              ) : (
                <>
                  <p className="mb-1 text-2xs text-fg-faint">{spans.length} caption{spans.length !== 1 ? "s" : ""} on the timeline</p>
                  {spans.map((s, i) => {
                    const rowHasWords = !!(s.caption.words && s.caption.words.length > 0);
                    return (
                      <div key={`${s.caption.id}-${i}`} className={cx("group rounded-lg border bg-panel2 p-2", selectedCaption === s.caption.id ? "border-primary" : "border-line")}>
                        <div className="mb-1 flex items-center justify-between">
                          <button onClick={() => { useStore.getState().setPreviewMode("edit"); useStore.getState().seek(s.outStart); }} className="text-2xs tabular-nums text-primary hover:underline">
                            {fmtTime(s.outStart, true)} – {fmtTime(s.outEnd, true)}
                          </button>
                          <span className="flex items-center gap-1 text-fg-faint">
                            {s.caption.manual && (
                              <button onClick={() => editEdl((e) => ({ ...e, captions: e.captions.map((c) => (c.id === s.caption.id ? resetCaption(c) : c)) }))}
                                title="Timing was changed by hand. Click to go back to the speech timing." className="rounded px-1 text-[10px] font-medium text-warn hover:bg-panel">
                                Reset
                              </button>
                            )}
                            <TimeInput label="Caption start (s)" value={s.outStart} onCommit={(d) => moveEdge(s.caption.id, "start", d)} />
                            <TimeInput label="Caption end (s)" value={s.outEnd} onCommit={(d) => moveEdge(s.caption.id, "end", d)} />
                          </span>
                          <div className="flex items-center gap-1">
                            {rowHasWords && (
                              <span className="rounded bg-primary/15 px-1 py-0.5 text-[9px] font-medium text-primary" title="Word-level timing available">
                                WORDS
                              </span>
                            )}
                            <button aria-label="Delete caption" onClick={() => editEdl((e) => ({ ...e, captions: e.captions.filter((c) => c.id !== s.caption.id) }))} className="text-fg-faint opacity-0 transition-opacity hover:text-danger group-hover:opacity-100">
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>
                        <textarea
                          value={s.caption.text}
                          aria-label="Caption text"
                          rows={Math.min(3, Math.ceil(s.caption.text.length / 34) || 1)}
                          onChange={(e) => {
                            const text = e.target.value;
                            editEdl((x) => ({ ...x, captions: x.captions.map((c) => (c.id === s.caption.id ? { ...c, text, words: c.words?.length ? retimeWords(text, c.srcStart, c.srcEnd) : null } : c)) }), `cap-${s.caption.id}`);
                          }}
                          className="w-full resize-none rounded border border-transparent bg-transparent px-1 text-xs text-fg outline-none focus:border-primary focus:bg-panel"
                        />
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

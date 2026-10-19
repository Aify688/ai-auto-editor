import {
  AlertTriangle, Briefcase, Camera, Captions, Check, ChevronDown, Clapperboard, Crop, Eye, EyeOff, Film, Layers, Loader2, Maximize2, Megaphone, Mountain, Music,
  RectangleHorizontal, RectangleVertical, RotateCw, Share2, Smartphone, Sparkles, Square, Star, VolumeX, Wand2, X, Zap,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cancelJob, isActive, retryJob, startAutoEdit, startJob } from "../../hooks/useJobs";
import { restoreRemoved } from "../../lib/edits";
import { setPrimaryMusic } from "../../lib/timelineOps";
import { fmtDuration } from "../../lib/format";
import { MAX_DESCRIPTION, generationState } from "../../lib/generation";
import { layout } from "../../lib/layout";
import { api } from "../../services/api";
import { ASPECTS, PRIMARY_STYLES, STYLES } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { AiSettings, Aspect, GenerationPlan, InstructionPlan, Job, ProjectDoc, Style } from "../../types";
import { ClipProperties } from "../panels/ClipProperties";
import { MusicRecommendations } from "../panels/MusicRecommendations";
import { Button, Field, Segmented, Select, Slider, Toggle, cx } from "../ui/controls";

const STYLE_ICON: Record<Style, typeof Zap> = {
  dynamic: Zap, cinematic: Clapperboard, vlog: Smartphone, travel: Mountain, marketing: Megaphone,
  social: Share2, professional: Briefcase, auto: Wand2, energetic: Zap, minimal: Square, documentary: Film,
};
const ASPECT_ICON: Record<Aspect, typeof Square> = {
  "16:9": RectangleHorizontal, "9:16": RectangleVertical, "1:1": Square, "4:5": RectangleVertical, original: Crop,
};

function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="border-t border-line px-4 py-3">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

function useSettings() {
  const updateDoc = useStore((s) => s.updateDoc);
  return (patch: Partial<AiSettings>, edlPatch?: (d: ProjectDoc) => ProjectDoc["edl"], coalesce?: string) =>
    updateDoc(
      (d) => {
        const next = { ...d, settings: { ...d.settings, ...patch } };
        return edlPatch && d.edl ? { ...next, edl: edlPatch(next) } : next;
      },
      { coalesce },
    );
}

function StylePicker() {
  const style = useStore((s) => s.doc!.style);
  const updateDoc = useStore((s) => s.updateDoc);
  const [more, setMore] = useState(!PRIMARY_STYLES.includes(style));
  const keys = (Object.keys(STYLES) as Style[]).filter((k) => (more ? true : PRIMARY_STYLES.includes(k)));
  const ordered = [...keys].sort((x, y) => {
    const ix = PRIMARY_STYLES.indexOf(x), iy = PRIMARY_STYLES.indexOf(y);
    return (ix < 0 ? 99 : ix) - (iy < 0 ? 99 : iy);
  });
  return (
    <div className="space-y-1.5" role="radiogroup" aria-label="Editing style">
      {ordered.map((key) => {
        const info = STYLES[key];
        const Icon = STYLE_ICON[key];
        const on = style === key;
        return (
          <button
            key={key}
            role="radio"
            aria-checked={on}
            onClick={() =>
              updateDoc((d) => (d.style === key ? d : { ...d, style: key, settings: { ...d.settings, ...info.defaults } }))
            }
            className={cx(
              "flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
              on ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]",
            )}
          >
            <div className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded", on ? "bg-primary text-primary-ink" : "bg-panel text-fg-muted")}>
              <Icon size={16} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-fg">{info.name}</span>
                <span className="text-2xs text-fg-faint">{info.bestFor}</span>
              </div>
              <div className="mt-0.5 truncate text-2xs text-fg-muted">{info.traits.join(" · ")}</div>
            </div>
          </button>
        );
      })}
      <button onClick={() => setMore(!more)} aria-expanded={more} className="w-full py-1 text-center text-2xs text-fg-muted hover:text-fg">
        {more ? "Fewer styles" : "More styles"}
      </button>
    </div>
  );
}

function FormatPicker() {
  const aspect = useStore((s) => s.doc!.aspect);
  const updateDoc = useStore((s) => s.updateDoc);
  return (
    <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Output format">
      {ASPECTS.map((a) => {
        const Icon = ASPECT_ICON[a.value];
        const on = aspect === a.value;
        return (
          <button
            key={a.value}
            role="radio"
            aria-checked={on}
            onClick={() => updateDoc((d) => ({ ...d, aspect: a.value, edl: d.edl && { ...d.edl, aspect: a.value } }))}
            className={cx(
              "flex flex-col items-center gap-1 rounded-md border py-2 transition-colors",
              on ? "border-primary bg-primary-muted text-primary" : "border-line bg-panel2 text-fg-muted hover:border-[#4A5160] hover:text-fg",
            )}
          >
            <Icon size={18} />
            <span className="text-xs font-medium text-fg">{a.label}</span>
            <span className="text-2xs">{a.hint}</span>
          </button>
        );
      })}
    </div>
  );
}

function AiOptions() {
  const st = useStore((s) => s.doc!.settings);
  const style = useStore((s) => s.doc!.style);
  const transcription = useStore((s) => s.system?.transcription);
  const set = useSettings();
  const beatAvailable = style === "dynamic" && !!st.musicId;
  const rows: { icon: typeof Star; label: string; hint: string; on: boolean; disabled?: boolean; onChange: (v: boolean) => void }[] = [
    { icon: Captions, label: "Auto captions", hint: transcription && !transcription.ok ? "Speech-to-text not installed" : "Local Whisper",
      on: st.captions, disabled: !transcription?.ok, onChange: (v) => set({ captions: v }) },
    { icon: VolumeX, label: "Remove silence", hint: "Tighten pauses", on: st.removeSilence, onChange: (v) => set({ removeSilence: v }) },
    { icon: Star, label: "Find highlights", hint: "Keep the best moments", on: st.highlightDetection, onChange: (v) => set({ highlightDetection: v }) },
    // Sensitivity slider is rendered separately below
    { icon: EyeOff, label: "Remove boring parts", hint: "Cut low-quality sections", on: st.boringRemoval, onChange: (v) => set({ boringRemoval: v }) },
    { icon: Layers, label: "Transitions", hint: "Between clips", on: st.transitions,
      onChange: (v) => set({ transitions: v }, (d) => ({ ...d.edl!, transition: v ? { ...STYLES[d.edl!.style].transition } : null })) },
    { icon: Music, label: "Beat sync", hint: beatAvailable ? "Cuts land on the beat" : "Dynamic style + music",
      on: st.beatSync && beatAvailable, disabled: !beatAvailable, onChange: (v) => set({ beatSync: v }) },
  ];
  const sensLabel = st.highlightSensitivity < 0.3 ? "Strict" : st.highlightSensitivity < 0.7 ? "Balanced" : "Inclusive";

  return (
    <div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-3 py-2">
          <div className="flex min-w-0 items-center gap-3">
            <r.icon size={16} className="shrink-0 text-fg-muted" />
            <div className="min-w-0">
              <div className="text-sm text-fg">{r.label}</div>
              <div className="truncate text-2xs text-fg-faint">{r.hint}</div>
            </div>
          </div>
          <Toggle label={r.label} checked={r.on} disabled={r.disabled} onChange={r.onChange} />
        </div>
      ))}
      {st.highlightDetection && (
        <div className="mt-1 rounded-lg border border-line bg-panel2 px-3 py-2.5">
          <div className="mb-1.5 flex items-center justify-between text-xs">
            <span className="text-fg-muted">Highlight sensitivity</span>
            <span className="text-2xs text-fg-faint">{sensLabel}</span>
          </div>
          <Slider
            label="Highlight sensitivity"
            min={0}
            max={1}
            step={0.05}
            value={st.highlightSensitivity ?? 0.5}
            onChange={(v) => set({ highlightSensitivity: v }, undefined, "highlight-sens")}
          />
          <div className="mt-1 flex justify-between text-2xs text-fg-faint">
            <span>Only the best</span>
            <span>Keep more</span>
          </div>
        </div>
      )}
    </div>
  );
}

const VIDEO_TYPE_INFO: Record<string, { icon: typeof Zap; label: string }> = {
  action: { icon: Zap, label: "Action" },
  talking_head: { icon: Camera, label: "Talking head" },
  scenic: { icon: Mountain, label: "Scenic" },
  mixed: { icon: Eye, label: "Mixed" },
};

function AiChanges() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const [open, setOpen] = useState(false);
  const removed = edl?.removed ?? [];
  const excluded = edl?.excluded ?? [];
  if (!removed.length && !excluded.length) return null;
  const name = (id: string) => media.find((m) => m.id === id)?.name ?? "Removed file";
  const total = removed.reduce((a, r) => a + (r.end - r.start), 0);
  const restore = (i: number) => {
    const r = removed[i];
    updateDoc((d) => (d.edl ? { ...d, edl: restoreRemoved(d.edl, i, name(r.mediaId)) } : d));
    toast("Segment restored. Render a preview to see it.", "success");
  };
  return (
    <div className="mt-3 border-t border-line pt-2">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between text-xs text-fg-muted hover:text-fg">
        <span>{removed.length} segment{removed.length === 1 ? "" : "s"} removed · {fmtDuration(total)}</span>
        <ChevronDown size={13} className={cx("transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ul className="mt-2 max-h-52 space-y-1.5 overflow-y-auto">
          {excluded.map((x) => (
            <li key={x.mediaId} className="text-2xs text-warn">{x.name}: {x.reason}</li>
          ))}
          {removed.map((r, i) => (
            <li key={`${r.mediaId}-${r.start}`} className="flex items-center gap-2 text-2xs">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-fg" title={name(r.mediaId)}>{name(r.mediaId)}</span>
                <span className="text-fg-faint">{r.start.toFixed(1)}–{r.end.toFixed(1)}s · {r.label}</span>
              </span>
              <Button size="sm" variant="ghost" onClick={() => restore(i)} aria-label={`Restore ${name(r.mediaId)} ${r.start.toFixed(1)} to ${r.end.toFixed(1)} seconds`}>Restore</Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Conflict() {
  const conflict = useStore((s) => s.doc?.edl?.conflict ?? null);
  const updateDoc = useStore((s) => s.updateDoc);
  if (!conflict) return null;
  return (
    <div className="mx-4 mb-4 rounded-lg border border-warn/40 bg-warn/10 p-3">
      <div className="flex gap-2 text-xs text-warn"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{conflict.message}</span></div>
      <Button size="sm" className="mt-2" onClick={() => updateDoc((d) => ({ ...d, settings: { ...d.settings, targetDuration: Math.ceil(conflict.suggested) } }))}>
        Use {Math.ceil(conflict.suggested)}s and regenerate
      </Button>
    </div>
  );
}

/** Plain-language request. With footage it steers the edit; without footage it is the video to generate. */
function InstructionBox() {
  const instruction = useStore((s) => s.doc!.settings.instruction ?? "");
  const hasVisual = useStore((s) => s.media.some((m) => m.kind !== "audio"));
  const updateDoc = useStore((s) => s.updateDoc);
  const [plan, setPlan] = useState<InstructionPlan | null>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!instruction.trim()) { setPlan(null); return; }
    let alive = true;
    const t = window.setTimeout(() => api.previewPlan(instruction).then((p) => alive && setPlan(p)).catch(() => undefined), 350);
    return () => { alive = false; window.clearTimeout(t); };
  }, [instruction]);
  const set = (v: string) => updateDoc((d) => ({ ...d, settings: { ...d.settings, instruction: v } }), { coalesce: "instruction" });
  const near = instruction.length > MAX_DESCRIPTION * 0.9;
  return (
    <div className="px-4 pb-4">
      <div className="mb-1.5 flex items-center justify-between">
        <label htmlFor="ai-instruction" className="block text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">
          {hasVisual ? "Describe your video" : "Describe the video"}{" "}
          {hasVisual && <span className="font-normal normal-case tracking-normal text-fg-faint">(optional)</span>}
        </label>
        <button onClick={() => setExpanded(true)} className="flex items-center gap-1 text-2xs text-fg-muted hover:text-fg" title="Open a larger editor">
          <Maximize2 size={11} /> Expand editor
        </button>
      </div>
      <textarea
        id="ai-instruction"
        maxLength={MAX_DESCRIPTION}
        value={instruction}
        onChange={(e) => set(e.target.value)}
        placeholder={hasVisual
          ? "e.g. Create a 30-second travel vlog with upbeat music, dynamic captions and smooth transitions."
          : "Describe the video to generate: the scenes, setting, mood, camera movement and style. Use a new paragraph for each scene."}
        className="block h-[200px] min-h-[180px] max-h-[60vh] w-full resize-y rounded-lg border border-line bg-app px-3 py-2 text-sm leading-5 text-fg outline-none placeholder:text-fg-faint focus:border-primary"
      />
      <div className={cx("mt-1 text-right text-2xs tabular-nums", near ? "text-warn" : "text-fg-faint")} aria-live="polite">
        {instruction.length.toLocaleString()} / {MAX_DESCRIPTION.toLocaleString()} characters
      </div>
      {plan && (plan.understood.length > 0 || plan.warnings.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5" aria-live="polite">
          {plan.understood.map((u) => <span key={u} className="rounded-full bg-primary-muted px-2 py-0.5 text-2xs text-primary">{u}</span>)}
          {plan.warnings.map((w) => <span key={w} className="rounded-full bg-warn/15 px-2 py-0.5 text-2xs text-warn">{w}</span>)}
        </div>
      )}
      {expanded && <ExpandedEditor value={instruction} onChange={set} onClose={() => setExpanded(false)} />}
    </div>
  );
}

function ExpandedEditor({ value, onChange, onClose }: { value: string; onChange: (v: string) => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" role="dialog" aria-modal="true" aria-label="Video description editor" onMouseDown={onClose}>
      <div className="flex h-[min(80vh,720px)] w-[min(820px,100%)] flex-col rounded-xl border border-line bg-panel p-4 shadow-2xl" onMouseDown={(e) => e.stopPropagation()}>
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-semibold text-fg">Video description</div>
          <button onClick={onClose} aria-label="Close editor" className="rounded p-1 text-fg-muted hover:bg-raise hover:text-fg"><X size={16} /></button>
        </div>
        <textarea
          autoFocus
          maxLength={MAX_DESCRIPTION}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="min-h-0 flex-1 resize-none rounded-lg border border-line bg-app px-3 py-2 text-sm leading-6 text-fg outline-none focus:border-primary"
          aria-label="Video description"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-2xs tabular-nums text-fg-faint">{value.length.toLocaleString()} / {MAX_DESCRIPTION.toLocaleString()} characters</span>
          <Button size="sm" variant="primary" onClick={onClose}>Done</Button>
        </div>
      </div>
    </div>
  );
}

/** Everything beyond the one-click path lives here, closed by default. */
function Customize({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const style = useStore((s) => s.doc!.style);
  const aspect = useStore((s) => s.doc!.aspect);
  return (
    <section className="border-t border-line">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center justify-between px-4 py-3 text-left">
        <span>
          <span className="block text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Customize</span>
          <span className="text-2xs text-fg-faint">{STYLES[style].name} · {aspect} · style, format and options</span>
        </span>
        <ChevronDown size={14} className={cx("text-fg-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && <div className="pb-1">{children}</div>}
    </section>
  );
}

function EditSummary() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  if (!edl || !edl.clips.length) return null;
  const vt = edl.videoType ? VIDEO_TYPE_INFO[edl.videoType] : null;
  const rejectedCount = edl.clips.filter((c) => c.rejected).length;
  const boringCount = edl.clips.filter((c) => c.boring).length;
  const chips = [
    `${edl.clips.length - rejectedCount - boringCount} clips`,
    fmtDuration(layout(edl).duration),
    STYLES[edl.style].name,
    vt ? vt.label : null,
    edl.beat ? `${Math.round(60 / edl.beat)} BPM` : null,
    edl.captions.length ? `${edl.captions.length} captions` : null,
    rejectedCount ? `${rejectedCount} rejected` : null,
    boringCount ? `${boringCount} boring removed` : null,
  ].filter(Boolean) as string[];
  return (
    <div className="mx-4 mb-4 rounded-lg border border-line bg-panel2 p-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-fg">
        <Check size={15} className="text-success" /> Edit ready
      </div>
      {vt && (
        <div className="mt-1.5 flex items-center gap-1.5 text-2xs text-fg-muted">
          <vt.icon size={11} /> Detected: {vt.label} content — weights adapted
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <span key={c} className="rounded-full bg-app px-2 py-0.5 text-2xs text-fg-muted">{c}</span>
        ))}
      </div>
      {edl.plan?.understood?.length ? (
        <div className="mt-2 text-2xs text-fg-faint">Understood: {edl.plan.understood.join(" · ")}</div>
      ) : null}
      <AiChanges />
    </div>
  );
}

function Advanced() {
  const [open, setOpen] = useState(false);
  const st = useStore((s) => s.doc!.settings);
  const audio = useStore((s) => s.media.filter((m) => m.kind === "audio" && m.status === "ready"));
  const set = useSettings();

  return (
    <section className="border-t border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between px-4 py-3 text-left" aria-expanded={open}>
        <span className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Advanced settings</span>
        <ChevronDown size={14} className={cx("text-fg-muted transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-0.5 px-4 pb-3">
          <Field label="Target duration" hint={st.targetDuration ? `${st.targetDuration}s` : "Chosen by style"}>
            <div className="flex items-center gap-2">
              <span className="text-2xs text-fg-muted">Auto</span>
              <Toggle label="Auto duration" checked={st.targetDuration == null} onChange={(v) => set({ targetDuration: v ? null : 30 })} />
            </div>
          </Field>
          {st.targetDuration != null && (
            <div className="pb-1">
              <Slider label="Target duration" min={5} max={180} step={1} value={st.targetDuration} onChange={(v) => set({ targetDuration: v }, undefined, "target")} />
            </div>
          )}
          <Field label="Preview quality">
            <Segmented label="Preview quality" value={st.resolution} onChange={(v) => set({ resolution: v })}
              options={[{ value: 720, label: "720p" }, { value: 1080, label: "1080p" }]} />
          </Field>
          <Field label="Background music" hint={audio.length ? undefined : "Upload MP3/WAV in Media"}>
            <Select
              label="Background music"
              className="w-36"
              value={st.musicId ?? ""}
              disabled={!audio.length}
              options={[{ value: "", label: "None" }, ...audio.map((m) => ({ value: m.id, label: m.name }))]}
              onChange={(v) =>
                set({ musicId: v || null }, (d) =>
                  setPrimaryMusic(d.edl!, v ? { mediaId: v, volume: d.settings.musicVolume } : null),
                )
              }
            />
          </Field>
          {st.musicId && (
            <Field label="Music volume" hint={`${Math.round(st.musicVolume * 100)}%`}>
              <div className="w-36">
                <Slider label="Music volume" min={0.05} max={1} step={0.05} value={st.musicVolume}
                  onChange={(v) => set({ musicVolume: v }, (d) => d.edl!.music ? setPrimaryMusic(d.edl!, { volume: v }) : d.edl, "musicvol")} />
              </div>
            </Field>
          )}
          {st.captions && (
            <Field label="Burn captions into video">
              <Toggle label="Burn captions" checked={st.burnCaptions} onChange={(v) => set({ burnCaptions: v }, (d) => ({ ...d.edl!, burnCaptions: v }))} />
            </Field>
          )}
          <Field label="Scene detection"><Toggle label="Scene detection" checked={st.sceneDetection} onChange={(v) => set({ sceneDetection: v })} /></Field>
          <Field label="Audio normalization">
            <Toggle label="Audio normalization" checked={st.normalizeAudio}
              onChange={(v) => set({ normalizeAudio: v }, (d) => ({ ...d.edl!, audio: { ...d.edl!.audio, normalize: v } }))} />
          </Field>
          <Field label="Smart cropping" hint={st.smartCrop ? "Follows faces & motion" : "Blurred background fit"}>
            <Toggle label="Smart cropping" checked={st.smartCrop} onChange={(v) => set({ smartCrop: v }, (d) => ({ ...d.edl!, fit: v ? "crop" : "blur" }))} />
          </Field>
        </div>
      )}
    </section>
  );
}

export function JobProgress({ job }: { job: Job }) {
  const idx = job.stages.findIndex((s) => s.key === job.stage);
  return (
    <div className="rounded-md border border-line bg-panel2 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-fg">{job.status === "queued" ? "Queued…" : "Generating your video"}</span>
        <span className="text-xs tabular-nums text-fg-muted">{Math.round(job.progress * 100)}%</span>
      </div>
      <div className="mb-3 h-1.5 overflow-hidden rounded bg-line">
        <div className="h-full rounded bg-primary transition-[width] duration-300" style={{ width: `${job.progress * 100}%` }} />
      </div>
      <ol className="space-y-1">
        {job.stages.map((s, i) => (
          <li key={s.key} className={cx("flex items-center gap-2 text-xs", i < idx ? "text-fg-muted" : i === idx ? "text-fg" : "text-fg-faint")}>
            {i < idx ? <Check size={12} className="text-success" /> : i === idx ? <Loader2 size={12} className="animate-spin text-primary" /> : <span className="h-3 w-3 rounded-full border border-line" />}
            {s.label}
          </li>
        ))}
      </ol>
      {job.message && <div className="mt-2 truncate text-2xs text-fg-faint" title={job.message}>{job.message}</div>}
      <Button size="sm" variant="ghost" className="mt-2 w-full" icon={<X size={12} />} onClick={() => cancelJob(job)}>
        Cancel
      </Button>
    </div>
  );
}

/** Debounced "what will Generate do" line for text-to-video, from the server's own planner. */
function useGenerationPlan(active: boolean): GenerationPlan | null {
  const instruction = useStore((s) => s.doc?.settings.instruction ?? "");
  const [plan, setPlan] = useState<GenerationPlan | null>(null);
  useEffect(() => {
    const { project, doc } = useStore.getState();
    if (!active || !project || !doc || !instruction.trim()) { setPlan(null); return; }
    let alive = true;
    const t = window.setTimeout(() => api.generationPlan(project.id, doc).then((p) => alive && setPlan(p)).catch(() => undefined), 600);
    return () => { alive = false; window.clearTimeout(t); };
  }, [active, instruction]);
  return plan;
}

function GenerateArea() {
  const job = useStore((s) => s.jobs.generate);
  const media = useStore((s) => s.media);
  const edl = useStore((s) => s.doc!.edl);
  const instruction = useStore((s) => s.doc!.settings.instruction ?? "");
  const t2v = useStore((s) => s.system?.textToVideo);
  const notes = edl?.notes ?? [];
  const [showNotes, setShowNotes] = useState(false);
  const visual = media.filter((m) => m.kind !== "audio");
  const running = isActive(job);
  const gen = generationState({
    visualCount: visual.length, readyCount: visual.filter((m) => m.status === "ready").length,
    processing: media.some((m) => m.status === "processing"), instruction, running, hasEdit: !!edl?.clips.length,
  });
  const blocked = gen.enabled ? null : gen.reason;
  const plan = useGenerationPlan(gen.mode === "text" && !running);

  return (
    <div className="space-y-2 border-t border-line bg-panel px-4 py-3">
      {running && job ? (
        <JobProgress job={job} />
      ) : (
        <>
          {job?.status === "failed" && (
            <div className="rounded-md border border-danger/40 bg-danger/10 p-2.5">
              <div className="flex gap-2 text-xs text-danger">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" />
                <span className="break-words">{job.error}</span>
              </div>
              <Button size="sm" className="mt-2" icon={<RotateCw size={12} />} onClick={() => retryJob(job)}>Retry</Button>
            </div>
          )}
          {job?.status === "cancelled" && <div className="text-2xs text-fg-muted">Generation cancelled.</div>}
          <Button
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!gen.enabled}
            title={blocked ?? undefined}
            icon={<Sparkles size={16} />}
            onClick={() => gen.mode === "edit" ? startAutoEdit() : startJob("generate")}
          >
            {gen.label}
          </Button>
          {gen.mode === "edit" && <div className="text-center text-2xs text-fg-faint">Automatically cut video, caption speech, and add music.</div>}
          {blocked && <div className="text-center text-2xs text-fg-faint">{blocked}</div>}
          {gen.mode === "text" && t2v && !t2v.configured && (
            <div className="flex gap-2 rounded-md border border-warn/40 bg-warn/10 p-2.5 text-2xs text-warn" role="status">
              <AlertTriangle size={13} className="mt-0.5 shrink-0" />
              <span className="break-words">{t2v.hint}</span>
            </div>
          )}
          {gen.mode === "text" && plan && (
            <div className="text-center text-2xs text-fg-muted" aria-live="polite">
              {plan.error ?? `${plan.sceneCount} AI scene${plan.sceneCount === 1 ? "" : "s"} · about ${plan.seconds}s${plan.notes?.length ? ` · ${plan.notes[0]}` : ""}`}
            </div>
          )}
          {edl && edl.clips.length > 0 && (
            <div>
              <button onClick={() => setShowNotes(!showNotes)} className="flex w-full items-center justify-between text-2xs text-fg-muted hover:text-fg" aria-expanded={showNotes}>
                <span className="flex items-center gap-1.5">
                  <Film size={11} /> {edl.clips.length} clips · {fmtDuration(layout(edl).duration)} · {STYLES[edl.style].name}
                </span>
                <span className="flex items-center gap-0.5">Edit decisions <ChevronDown size={11} className={cx("transition-transform", showNotes && "rotate-180")} /></span>
              </button>
              {showNotes && (
                <ul className="mt-1.5 max-h-40 space-y-1 overflow-y-auto rounded bg-panel2 p-2">
                  {notes.map((n, i) => (
                    <li key={i} className="text-2xs leading-4 text-fg-muted">• {n}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function AiEditPanel() {
  const [tab, setTab] = useState<"ai" | "props">("ai");
  const selected = useStore((s) => s.selectedClipId);
  const audioSelected = useStore((s) => s.selectedAudioId);
  useEffect(() => {
    if (selected || audioSelected) setTab("props");
  }, [selected, audioSelected]);
  return (
    <aside className="flex w-[340px] shrink-0 flex-col border-l border-line bg-panel" aria-label="AI Auto Edit">
      <div className="px-4 pb-3 pt-3">
        <Segmented
          label="Panel"
          value={tab}
          onChange={setTab}
          options={[{ value: "ai", label: "AI Edit" }, { value: "props", label: "Properties" }]}
        />
      </div>
      {tab === "ai" ? (
        <>
          <div className="flex-1 overflow-y-auto">
            <InstructionBox />
            <EditSummary />
            <Conflict />
            <div className="px-4"><MusicRecommendations compact /></div>
            <Customize>
              <Section title="Editing style"><StylePicker /></Section>
              <Section title="Output format"><FormatPicker /></Section>
              <Section title="AI options"><AiOptions /></Section>
              <Advanced />
            </Customize>
          </div>
          <GenerateArea />
        </>
      ) : (
        <div className="flex-1 overflow-y-auto px-4 pb-4">
          <ClipProperties />
        </div>
      )}
    </aside>
  );
}

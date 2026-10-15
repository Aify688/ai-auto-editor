import {
  AlertTriangle, Captions, Check, ChevronDown, Clapperboard, Film, Layers, Loader2, Music, RectangleHorizontal, RectangleVertical,
  RotateCw, Smartphone, Sparkles, Square, Star, VolumeX, X, Zap,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cancelJob, isActive, retryJob, startJob } from "../../hooks/useJobs";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { ASPECTS, STYLES } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { AiSettings, Aspect, Job, ProjectDoc, Style } from "../../types";
import { ClipProperties } from "../panels/ClipProperties";
import { Button, Field, Segmented, Select, Slider, Toggle, cx } from "../ui/controls";

const STYLE_ICON: Record<Style, typeof Zap> = { dynamic: Zap, cinematic: Clapperboard, vlog: Smartphone };
const ASPECT_ICON: Record<Aspect, typeof Square> = { "16:9": RectangleHorizontal, "9:16": RectangleVertical, "1:1": Square };

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
  return (
    <div className="space-y-1.5" role="radiogroup" aria-label="Editing style">
      {(Object.keys(STYLES) as Style[]).map((key) => {
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
    { icon: Layers, label: "Transitions", hint: "Between clips", on: st.transitions,
      onChange: (v) => set({ transitions: v }, (d) => ({ ...d.edl!, transition: v ? { ...STYLES[d.edl!.style].transition } : null })) },
    { icon: Music, label: "Beat sync", hint: beatAvailable ? "Cuts land on the beat" : "Dynamic style + music",
      on: st.beatSync && beatAvailable, disabled: !beatAvailable, onChange: (v) => set({ beatSync: v }) },
  ];
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
    </div>
  );
}

function EditSummary() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  if (!edl || !edl.clips.length) return null;
  const chips = [
    `${edl.clips.length} clips`,
    fmtDuration(layout(edl).duration),
    STYLES[edl.style].name,
    edl.beat ? `${Math.round(60 / edl.beat)} BPM` : null,
    edl.captions.length ? `${edl.captions.length} captions` : null,
  ].filter(Boolean) as string[];
  return (
    <div className="mx-4 mb-4 rounded-lg border border-line bg-panel2 p-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-fg">
        <Check size={15} className="text-success" /> Edit ready
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <span key={c} className="rounded-full bg-app px-2 py-0.5 text-2xs text-fg-muted">{c}</span>
        ))}
      </div>
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
                set({ musicId: v || null }, (d) => ({
                  ...d.edl!,
                  music: v ? { mediaId: v, volume: d.settings.musicVolume, duck: d.edl!.music?.duck ?? true } : null,
                }))
              }
            />
          </Field>
          {st.musicId && (
            <Field label="Music volume" hint={`${Math.round(st.musicVolume * 100)}%`}>
              <div className="w-36">
                <Slider label="Music volume" min={0.05} max={1} step={0.05} value={st.musicVolume}
                  onChange={(v) => set({ musicVolume: v }, (d) => d.edl!.music ? { ...d.edl!, music: { ...d.edl!.music, volume: v } } : d.edl, "musicvol")} />
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

function GenerateArea() {
  const job = useStore((s) => s.jobs.generate);
  const media = useStore((s) => s.media);
  const edl = useStore((s) => s.doc!.edl);
  const notes = edl?.notes ?? [];
  const [showNotes, setShowNotes] = useState(false);
  const visual = media.filter((m) => m.kind !== "audio");
  const processing = media.some((m) => m.status === "processing");
  const ready = visual.some((m) => m.status === "ready");
  const running = isActive(job);
  const blocked = !visual.length ? "Upload a video or image first" : processing ? "Waiting for media processing…" : !ready ? "No usable media" : null;

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
            disabled={!!blocked}
            title={blocked ?? undefined}
            icon={<Sparkles size={16} />}
            onClick={() => startJob("generate")}
          >
            {edl?.clips.length ? "Regenerate AI Video" : "Generate AI Video"}
          </Button>
          {blocked && <div className="text-center text-2xs text-fg-faint">{blocked}</div>}
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
  useEffect(() => {
    if (selected) setTab("props");
  }, [selected]);
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
            <EditSummary />
            <Section title="Editing style"><StylePicker /></Section>
            <Section title="Output format"><FormatPicker /></Section>
            <Section title="AI options"><AiOptions /></Section>
            <Advanced />
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

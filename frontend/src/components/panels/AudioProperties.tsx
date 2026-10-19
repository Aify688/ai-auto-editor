import { Copy, Music, Repeat, Scissors, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AUDIO_EFFECTS } from "../../lib/audioEffects";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { audioLength, duplicateAudio, laneOthers, moveAudio, splitAudio, trimAudioEnd, trimAudioStart, withAudioClips } from "../../lib/timelineOps";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { AudioClip, MusicLibraryTrack } from "../../types";
import { Button, Empty, Field, Select, Slider, Toggle } from "../ui/controls";

function Secs({ label, value, min, max, onCommit }: { label: string; value: number; min: number; max: number; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState(value.toFixed(2));
  useEffect(() => setDraft(value.toFixed(2)), [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n)) onCommit(Math.min(max, Math.max(min, n)));
    else setDraft(value.toFixed(2));
  };
  return (
    <input aria-label={label} inputMode="decimal" value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className="h-8 w-24 rounded-lg border border-line bg-app px-2 text-right text-xs tabular-nums text-fg outline-none focus:border-primary" />
  );
}

/** Properties of the audio/music clip selected on the timeline. Every change goes through the same rules as dragging. */
export function AudioProperties() {
  const id = useStore((s) => s.selectedAudioId);
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const time = useStore((s) => s.time);
  const updateDoc = useStore((s) => s.updateDoc);
  const selectAudio = useStore((s) => s.selectAudio);
  const toast = useStore((s) => s.toast);
  const [library, setLibrary] = useState<MusicLibraryTrack[]>([]);
  useEffect(() => { api.musicLibrary().then(setLibrary).catch(() => undefined); }, []);
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const c = edl?.audioClips.find((x) => x.id === id);

  if (!edl || !lay || !c) return <Empty icon={<Music size={18} />} title="No audio selected" text="Click a music or audio clip on the timeline." />;

  const total = lay.duration;
  const dur = (mid: string) => media.find((m) => m.id === mid)?.duration ?? library.find((t) => t.id === mid)?.duration ?? undefined;
  const srcDur = dur(c.mediaId);
  const len = audioLength(c, srcDur, total);
  const ctx = (pps = 100) => ({ total, pps, points: [] as number[], srcDur, others: laneOthers(edl.audioClips, c.id, dur, total) });
  const put = (next: AudioClip, key?: string) =>
    updateDoc((d) => (d.edl ? { ...d, edl: withAudioClips(d.edl, d.edl.audioClips.map((x) => (x.id === c.id ? next : x))) } : d), { coalesce: key ? `${key}-${c.id}` : undefined });
  const uploads = media.filter((m) => m.kind === "audio" && m.status === "ready");
  const options = [...uploads.map((m) => ({ value: m.id, label: m.name })), ...library.map((t) => ({ value: t.id, label: `${t.title} (library)` }))];
  if (!options.some((o) => o.value === c.mediaId)) options.unshift({ value: c.mediaId, label: "Current track" });
  const name = options.find((o) => o.value === c.mediaId)?.label ?? "Audio";
  const maxFade = Math.max(0.1, Math.min(10, len / 2));

  const split = () => {
    const parts = splitAudio(c, time, { srcDur, total });
    if (!parts) return toast("Move the playhead inside this clip (at least 0.2 s from its edges) to split it.");
    updateDoc((d) => (d.edl ? { ...d, edl: withAudioClips(d.edl, d.edl.audioClips.flatMap((x) => (x.id === c.id ? parts : [x]))) } : d));
    selectAudio(parts[1].id);
  };
  const duplicate = () => {
    const copy = duplicateAudio(c, { srcDur, total, others: ctx().others });
    if (!copy) return toast("There is no free space after this clip for a copy.");
    updateDoc((d) => (d.edl ? { ...d, edl: withAudioClips(d.edl, [...d.edl.audioClips, copy]) } : d));
    selectAudio(copy.id);
  };
  const remove = () => {
    updateDoc((d) => (d.edl ? { ...d, settings: c.kind === "music" ? { ...d.settings, musicId: null, musicSource: "none" } : d.settings, edl: withAudioClips(d.edl, d.edl.audioClips.filter((x) => x.id !== c.id)) } : d));
    selectAudio(null);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-clip-audio text-white"><Music size={18} /></div>
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-fg-faint">{c.kind === "music" ? "Music" : "Audio"} clip</div>
          <div className="truncate text-base font-semibold text-fg">{name}</div>
        </div>
      </div>

      <section className="rounded-xl border border-line bg-panel2 px-3 py-1">
        <Field label="Track">
          <Select label="Audio track" className="w-44" value={c.mediaId} options={options}
            onChange={(v) => put({ ...c, mediaId: v, trimIn: 0, loop: c.loop })} />
        </Field>
        <Field label="Starts at" hint="timeline, seconds">
          <Secs label="Start" value={c.start} min={0} max={Math.max(0, total - 0.2)} onCommit={(v) => put(moveAudio(c, v - c.start, ctx()).clip)} />
        </Field>
        <Field label="Length" hint={`${fmtDuration(len)} shown`}>
          <Secs label="Length" value={len} min={0.2} max={Math.max(0.2, c.loop ? total - c.start : Math.min(total - c.start, (srcDur ?? total) - c.trimIn))}
            onCommit={(v) => put(trimAudioEnd(c, v - len, ctx()).clip)} />
        </Field>
        <Field label="Source in" hint={srcDur ? `of ${fmtDuration(srcDur)}` : "seconds"}>
          <Secs label="Source in" value={c.trimIn} min={0} max={Math.max(0, (srcDur ?? 1e6) - 0.2)} onCommit={(v) => put(trimAudioStart(c, v - c.trimIn, ctx()).clip)} />
        </Field>
      </section>

      <section className="rounded-xl border border-line bg-panel2 px-3 py-2">
        <div className="py-1">
          <div className="mb-1 flex justify-between text-xs"><span>Volume</span><span className="tabular-nums text-fg-muted">{Math.round(c.volume * 100)}%</span></div>
          <Slider label="Volume" min={0} max={1} step={0.01} value={c.volume}
            onChange={(v) => updateDoc((d) => (d.edl ? { ...d, settings: c.kind === "music" ? { ...d.settings, musicVolume: Math.max(0.02, v) } : d.settings, edl: withAudioClips(d.edl, d.edl.audioClips.map((x) => (x.id === c.id ? { ...x, volume: v } : x))) } : d), { coalesce: `vol-${c.id}` })} />
          <Field label="Effect" hint={AUDIO_EFFECTS.find((a) => a.value === (c.effect ?? "none"))?.hint}>
            <Select label="Audio effect" className="w-36" value={c.effect ?? "none"} options={AUDIO_EFFECTS.map((a) => ({ value: a.value, label: a.label }))} onChange={(v) => put({ ...c, effect: v }, "afx")} />
          </Field>
        </div>
        <div className="py-1">
          <div className="mb-1 flex justify-between text-xs"><span>Fade in</span><span className="tabular-nums text-fg-muted">{c.fadeIn.toFixed(1)}s</span></div>
          <Slider label="Fade in" min={0} max={maxFade} step={0.1} value={Math.min(c.fadeIn, maxFade)} onChange={(v) => put({ ...c, fadeIn: v }, "fi")} />
        </div>
        <div className="py-1">
          <div className="mb-1 flex justify-between text-xs"><span>Fade out</span><span className="tabular-nums text-fg-muted">{c.fadeOut.toFixed(1)}s</span></div>
          <Slider label="Fade out" min={0} max={maxFade} step={0.1} value={Math.min(c.fadeOut, maxFade)} onChange={(v) => put({ ...c, fadeOut: v }, "fo")} />
        </div>
        <Field label="Loop" hint="Repeat to fill the length">
          <Toggle label="Loop" checked={c.loop} onChange={(v) => put({ ...c, loop: v })} />
        </Field>
        <Field label="Duck under speech" hint="Lowers it while someone talks">
          <Toggle label="Duck under speech" checked={c.duck} onChange={(v) => put({ ...c, duck: v })} />
        </Field>
      </section>

      <div className="grid grid-cols-3 gap-2">
        <Button icon={<Scissors size={13} />} onClick={split}>Split</Button>
        <Button icon={<Copy size={13} />} onClick={duplicate}>Duplicate</Button>
        <Button variant="danger" icon={<Trash2 size={13} />} onClick={remove}>Delete</Button>
      </div>
      <p className="flex items-center gap-1.5 text-2xs text-fg-faint"><Repeat size={11} /> Drag the clip or its edges on the timeline. Alt+←/→ nudges it.</p>
    </div>
  );
}

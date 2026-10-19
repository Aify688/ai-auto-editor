import { AlertCircle, Check, Diamond, Plus, Scissors, SlidersHorizontal, ThumbsDown, ThumbsUp, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MIN_CLIP, SPEEDS, trimClip } from "../../lib/edits";
import { fmtDuration } from "../../lib/format";
import { AUDIO_EFFECTS } from "../../lib/audioEffects";
import { addKeyframe, KF_DEFAULTS, updateKeyframe, valuesAt, type KfProp } from "../../lib/keyframes";
import { clipDuration, layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import type { EdlClip } from "../../types";
import { timelineActions } from "../timeline/Timeline";
import { Button, Empty, Field, Select, Slider, cx } from "../ui/controls";
import { BackgroundRemoval } from "./BackgroundRemoval";
import { AudioProperties } from "./AudioProperties";

/** Seconds input that commits on blur/Enter so a half-typed value is never clamped mid-edit. */
function SecondsInput({ label, value, min, max, onCommit }: {
  label: string; value: number; min: number; max: number; onCommit: (v: number) => void;
}) {
  const [draft, setDraft] = useState(value.toFixed(2));
  useEffect(() => setDraft(value.toFixed(2)), [value]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n)) onCommit(Math.min(max, Math.max(min, n)));
    else setDraft(value.toFixed(2));
  };
  return (
    <input
      aria-label={label}
      inputMode="decimal"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className="h-8 w-24 rounded-lg border border-line bg-app px-2 text-right text-xs tabular-nums text-fg outline-none focus:border-primary"
    />
  );
}

/** Properties of the selected timeline clip. Edits only fields the EDL really has. */
export function ClipProperties() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const selected = useStore((s) => s.selectedClipId);
  const updateDoc = useStore((s) => s.updateDoc);
  const audioSelected = useStore((s) => s.selectedAudioId);
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const laid = lay?.clips.find((c) => c.clip.id === selected);

  if (audioSelected) return <AudioProperties />;

  if (!laid)
    return <Empty icon={<SlidersHorizontal size={18} />} title="No clip selected" text="Select a clip on the timeline to adjust it." />;

  const { clip } = laid;
  const source = media.find((m) => m.id === clip.mediaId);
  const srcDur = source?.duration ?? clip.srcEnd;

  const trim = (edge: "start" | "end", v: number) =>
    updateDoc((d) => (d.edl ? { ...d, edl: trimClip(d.edl, clip.id, edge, v, srcDur) } : d), { coalesce: `trim-${clip.id}-${edge}` });
  const patch = (p: Partial<EdlClip>, key: string) =>
    updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, clips: d.edl.clips.map((c) => (c.id === clip.id ? { ...c, ...p } : c)) } } : d), { coalesce: key });

  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-fg-faint">Clip {laid.index + 1}</div>
        <input
          aria-label="Clip label"
          value={clip.label}
          maxLength={80}
          onChange={(e) => patch({ label: e.target.value }, `label-${clip.id}`)}
          className="mt-1 h-8 w-full rounded-lg border border-transparent bg-transparent px-1 text-base font-semibold text-fg outline-none hover:border-line focus:border-primary focus:bg-app"
        />
        <div className="truncate px-1 text-xs text-fg-faint" title={source?.name}>{source?.name ?? "–"}</div>
      </div>

      <section className="rounded-xl border border-line bg-panel2 px-3 py-1">
        <h3 className="pt-2 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Trim</h3>
        <Field label="Source in" hint="seconds">
          <SecondsInput label="Source in" value={clip.srcStart} min={0} max={clip.srcEnd - MIN_CLIP} onCommit={(v) => trim("start", v)} />
        </Field>
        <Field label="Source out" hint={`of ${fmtDuration(srcDur)}`}>
          <SecondsInput label="Source out" value={clip.srcEnd} min={clip.srcStart + MIN_CLIP} max={srcDur} onCommit={(v) => trim("end", v)} />
        </Field>
        <Field label="Length">
          <span className="text-xs tabular-nums text-fg">{fmtDuration(clipDuration(clip))}</span>
        </Field>
      </section>

      {clip.freeze ? (
        <section className="rounded-xl border border-line bg-panel2 px-3 py-1">
          <h3 className="pt-2 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Freeze frame</h3>
          <Field label="Hold" hint="seconds">
            <SecondsInput label="Freeze hold" value={clip.freeze} min={0.1} max={30} onCommit={(v) => patch({ freeze: v }, `freeze-${clip.id}`)} />
          </Field>
        </section>
      ) : (
        <section className="rounded-xl border border-line bg-panel2 px-3 py-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Speed</h3>
            <span className="text-xs tabular-nums text-fg">{(clip.speed ?? 1).toFixed(2)}x</span>
          </div>
          <div className="mt-2">
            <Slider label="Clip speed" min={0.25} max={4} step={0.05} value={clip.speed ?? 1} onChange={(v) => patch({ speed: v }, `speed-${clip.id}`)} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => patch({ speed: s }, `speed-${clip.id}`)}
                className={cx("rounded-md border px-1.5 py-0.5 text-2xs tabular-nums", (clip.speed ?? 1) === s ? "border-primary text-fg" : "border-line text-fg-muted hover:text-fg")}
              >
                {s}x
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-2xs text-fg-faint">Audio pitch is kept. Captions follow the new timing.</p>
        </section>
      )}

      {source?.hasAudio && !clip.freeze && (
        <section className="rounded-xl border border-line bg-panel2 px-3 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Clip audio</h3>
          <div className="mt-2 flex justify-between text-xs"><span>Volume</span><span className="tabular-nums text-fg-muted">{Math.round((clip.volume ?? 1) * 100)}%</span></div>
          <Slider label="Clip volume" min={0} max={2} step={0.05} value={clip.volume ?? 1} onChange={(v) => patch({ volume: v }, `vol-${clip.id}`)} />
          <Field label="Effect" hint={AUDIO_EFFECTS.find((a) => a.value === (clip.audioEffect ?? "none"))?.hint}>
            <Select label="Audio effect" className="w-36" value={clip.audioEffect ?? "none"} options={AUDIO_EFFECTS.map((a) => ({ value: a.value, label: a.label }))} onChange={(v) => patch({ audioEffect: v }, `afx-${clip.id}`)} />
          </Field>
        </section>
      )}

      <KeyframeSection clip={clip} outStart={laid.outStart} patch={patch} />

      {(
        <section className="rounded-xl border border-line bg-panel2 px-3 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Crop focus</h3>
          <p className="mb-2 mt-0.5 text-2xs text-fg-faint">Where smart crop keeps the frame centered.</p>
          <div className="space-y-2">
            <div>
              <div className="mb-1 flex justify-between text-xs"><span>Horizontal</span><span className="tabular-nums text-fg-muted">{Math.round(clip.focusX * 100)}%</span></div>
              <Slider label="Horizontal focus" min={0} max={1} step={0.01} value={clip.focusX} onChange={(v) => patch({ focusX: v }, `fx-${clip.id}`)} />
            </div>
            <div>
              <div className="mb-1 flex justify-between text-xs"><span>Vertical</span><span className="tabular-nums text-fg-muted">{Math.round(clip.focusY * 100)}%</span></div>
              <Slider label="Vertical focus" min={0} max={1} step={0.01} value={clip.focusY} onChange={(v) => patch({ focusY: v }, `fy-${clip.id}`)} />
            </div>
          </div>
        </section>
      )}

      {source?.kind === "video" && <BackgroundRemoval clip={clip} outStart={laid.outStart} patch={patch} />}

      <section className="rounded-xl border border-line bg-panel2 px-3 py-2">
        <h3 className="pt-1 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Highlight score</h3>
        <div className="mt-1 flex items-center justify-between">
          <span className="text-xs text-fg-muted">Overall</span>
          <span className="text-sm font-semibold tabular-nums text-fg">{clip.score != null ? clip.score.toFixed(2) : "–"}</span>
        </div>
        {clip.score != null && (
          <div className="mt-1 h-1.5 overflow-hidden rounded bg-line">
            <div className="h-full rounded bg-primary" style={{ width: `${Math.min(100, clip.score * 100)}%` }} />
          </div>
        )}
        {clip.scoreBreakdown && (
          <div className="mt-2 space-y-1">
            {Object.entries(clip.scoreBreakdown)
              .filter(([k]) => k !== "steady")
              .map(([key, val]) => {
                const labels: Record<string, string> = {
                  motion: "Motion", sharp: "Sharpness", audio: "Audio energy",
                  activity: "Speech activity", face: "Face presence",
                };
                return (
                  <div key={key}>
                    <div className="flex items-center justify-between text-2xs">
                      <span className="text-fg-muted">{labels[key] ?? key}</span>
                      <span className="tabular-nums text-fg-faint">{(val * 100).toFixed(0)}%</span>
                    </div>
                    <div className="mt-0.5 h-1 overflow-hidden rounded bg-line">
                      <div className="h-full rounded bg-fg-muted/40" style={{ width: `${val * 100}%` }} />
                    </div>
                  </div>
                );
              })}
          </div>
        )}
        <div className="mt-1.5 flex items-center justify-between py-1">
          <span className="text-xs text-fg-muted">Starts at</span>
          <span className="text-xs tabular-nums text-fg">{fmtDuration(laid.outStart)}</span>
        </div>
      </section>

      {clip.boring && (
        <section className="rounded-xl border border-warning/40 bg-warning/10 px-3 py-2.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-warning">
            <AlertCircle size={14} /> Boring section detected
          </div>
          <p className="mt-1 text-2xs text-fg-muted">
            {clip.boringReason === "low_motion" && "Very little movement — static or near-still footage."}
            {clip.boringReason === "silent" && "No meaningful audio activity detected."}
            {clip.boringReason === "blurry" && "Out of focus or blurry — low visual sharpness."}
            {clip.boringReason === "static" && "Static shot with no speech or action."}
            {clip.boringReason === "low_energy" && "Low energy across audio and visual signals."}
            {!clip.boringReason && "Multiple quality signals are below threshold."}
          </p>
          <Button
            size="sm"
            className="mt-2 w-full"
            icon={<Check size={12} />}
            onClick={() => patch({ boring: false, boringReason: null }, `unbore-${clip.id}`)}
          >
            Keep this clip anyway
          </Button>
        </section>
      )}

      {clip.score != null && (
        <div className="flex gap-2">
          <Button
            className={cx("flex-1", !clip.rejected && "border-success/50 text-success")}
            variant="secondary"
            icon={clip.rejected ? <ThumbsUp size={14} /> : <Check size={14} />}
            onClick={() => patch({ rejected: false }, `accept-${clip.id}`)}
            disabled={!clip.rejected}
          >
            {clip.rejected ? "Restore" : "Accepted"}
          </Button>
          <Button
            className={cx("flex-1", clip.rejected && "border-danger/50 text-danger")}
            variant="secondary"
            icon={clip.rejected ? <X size={14} /> : <ThumbsDown size={14} />}
            onClick={() => patch({ rejected: true }, `reject-${clip.id}`)}
            disabled={clip.rejected}
          >
            {clip.rejected ? "Rejected" : "Reject"}
          </Button>
        </div>
      )}

      <div className="flex gap-2">
        <Button className="flex-1" icon={<Scissors size={14} />} onClick={() => timelineActions.split?.()}>Split</Button>
        <Button className="flex-1" variant="danger" icon={<Trash2 size={14} />} onClick={() => timelineActions.remove?.()}>Delete</Button>
      </div>
    </div>
  );
}

const KF_CONTROLS: { prop: KfProp; label: string; min: number; max: number; step: number; fmt: (v: number) => string }[] = [
  { prop: "scale", label: "Scale", min: 0.1, max: 3, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { prop: "x", label: "Position X", min: -1, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { prop: "y", label: "Position Y", min: -1, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
  { prop: "rotation", label: "Rotation", min: -180, max: 180, step: 1, fmt: (v) => `${Math.round(v)}°` },
  { prop: "opacity", label: "Opacity", min: 0, max: 1, step: 0.01, fmt: (v) => `${Math.round(v * 100)}%` },
];

/** Keyframe animation of the selected clip: add a keyframe at the playhead, then edit its values. */
function KeyframeSection({ clip, outStart, patch }: { clip: EdlClip; outStart: number; patch: (p: Partial<EdlClip>, key: string) => void }) {
  const time = useStore((s) => s.time);
  const seek = useStore((s) => s.seek);
  const [picked, setPicked] = useState<number | null>(null);
  const kfs = clip.keyframes ?? [];
  const dur = clipDuration(clip);
  const local = Math.min(dur, Math.max(0, time - outStart));
  const inside = time >= outStart && time <= outStart + dur;
  // sliders show the animated value at the playhead; moving one writes a keyframe there
  const shown = picked != null && kfs[picked] ? kfs[picked] : valuesAt(kfs, local);

  const setValue = (prop: KfProp, v: number) => {
    if (picked != null && kfs[picked]) return patch({ keyframes: updateKeyframe(kfs, picked, { [prop]: v }) }, `kf-${clip.id}-${picked}-${prop}`);
    if (!kfs.length) {
      const next = addKeyframe([{ t: 0, ...KF_DEFAULTS }], local, dur).map((k) => (Math.abs(k.t - local) < 0.05 ? { ...k, [prop]: v } : k));
      return patch({ keyframes: next }, `kf-${clip.id}`);
    }
    const next = addKeyframe(kfs, local, dur);
    const i = next.findIndex((k) => Math.abs(k.t - local) < 0.05);
    setPicked(i);
    patch({ keyframes: updateKeyframe(next, i, { [prop]: v }) }, `kf-${clip.id}`);
  };

  return (
    <section className="rounded-xl border border-line bg-panel2 px-3 py-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Animation</h3>
        <Button size="sm" icon={<Plus size={12} />} disabled={!inside} onClick={() => { const n = addKeyframe(kfs, local, dur); patch({ keyframes: n }, `kf-add-${clip.id}-${Date.now()}`); setPicked(n.findIndex((k) => Math.abs(k.t - local) < 0.05)); }}>
          Keyframe
        </Button>
      </div>
      <p className="mb-2 mt-0.5 text-2xs text-fg-faint">
        {inside ? "Move the playhead, add a keyframe and change a value. The clip animates between keyframes." : "Move the playhead onto this clip to add keyframes."}
      </p>
      {kfs.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-1">
          {kfs.map((k, i) => (
            <button
              key={k.t}
              onClick={() => { setPicked(i === picked ? null : i); seek(outStart + k.t); }}
              className={cx("flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs tabular-nums", i === picked ? "border-primary text-fg" : "border-line text-fg-muted hover:text-fg")}
            >
              <Diamond size={9} fill="currentColor" /> {k.t.toFixed(1)}s
            </button>
          ))}
        </div>
      )}
      <div className="space-y-2">
        {KF_CONTROLS.map((c) => (
          <div key={c.prop}>
            <div className="mb-1 flex justify-between text-xs"><span>{c.label}</span><span className="tabular-nums text-fg-muted">{c.fmt(shown[c.prop])}</span></div>
            <Slider label={c.label} min={c.min} max={c.max} step={c.step} value={shown[c.prop]} onChange={(v) => setValue(c.prop, v)} disabled={!inside && picked == null} />
          </div>
        ))}
      </div>
      {picked != null && kfs[picked] && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" className="flex-1" onClick={() => patch({ keyframes: updateKeyframe(kfs, picked, { ease: kfs[picked].ease === "smooth" ? "linear" : "smooth" }) }, `kf-ease-${clip.id}-${Date.now()}`)}>
            Ease: {kfs[picked].ease === "smooth" ? "smooth" : "linear"}
          </Button>
          <Button size="sm" variant="danger" className="flex-1" icon={<Trash2 size={12} />} onClick={() => { patch({ keyframes: kfs.filter((_, i) => i !== picked) }, `kf-del-${clip.id}-${Date.now()}`); setPicked(null); }}>
            Remove
          </Button>
        </div>
      )}
    </section>
  );
}

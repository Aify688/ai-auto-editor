import { Scissors, SlidersHorizontal, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { MIN_CLIP, trimClip } from "../../lib/edits";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import type { EdlClip } from "../../types";
import { timelineActions } from "../timeline/Timeline";
import { Button, Empty, Field, Slider } from "../ui/controls";

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
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const laid = lay?.clips.find((c) => c.clip.id === selected);

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
          <span className="text-xs tabular-nums text-fg">{fmtDuration(clip.srcEnd - clip.srcStart)}</span>
        </Field>
      </section>

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

      <dl className="divide-y divide-line rounded-xl border border-line bg-panel2">
        {([["Starts at", fmtDuration(laid.outStart)], ["Score", clip.score != null ? clip.score.toFixed(2) : "–"]] as [string, string][]).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 px-3 py-2">
            <dt className="text-xs text-fg-muted">{k}</dt>
            <dd className="text-xs tabular-nums text-fg">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="flex gap-2">
        <Button className="flex-1" icon={<Scissors size={14} />} onClick={() => timelineActions.split?.()}>Split</Button>
        <Button className="flex-1" variant="danger" icon={<Trash2 size={14} />} onClick={() => timelineActions.remove?.()}>Delete</Button>
      </div>
    </div>
  );
}

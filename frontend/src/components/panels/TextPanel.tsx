import { Copy, Plus, Trash2, Type } from "lucide-react";
import { useEffect, useState } from "react";
import { uid } from "../../lib/format";
import { layout } from "../../lib/layout";
import { titleLook, TITLE_DEFAULTS } from "../../lib/styles";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { FontFamily, TextAnimation, Title } from "../../types";
import { Button, Empty, Field, PanelHeader, Segmented, Select, Slider, Toggle, cx } from "../ui/controls";
import { editEdl } from "./shared";

const ANIMATIONS: { value: TextAnimation; label: string }[] = [
  { value: "none", label: "None" }, { value: "fade", label: "Fade" }, { value: "pop", label: "Pop" },
  { value: "scale", label: "Scale" }, { value: "slide", label: "Slide" },
];
const ALIGNS = [{ value: "left" as const, label: "Left" }, { value: "center" as const, label: "Center" }, { value: "right" as const, label: "Right" }];
const PRESETS = [{ value: "top" as const, y: 0.12, label: "Top" }, { value: "center" as const, y: 0.5, label: "Middle" }, { value: "bottom" as const, y: 0.88, label: "Bottom" }];

function Num({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void }) {
  return (
    <input type="number" aria-label={label} min={min} max={max} step={step} value={Number(value.toFixed(2))}
      onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || 0)))}
      className="h-7 w-16 rounded-lg border border-line bg-app px-1.5 text-right text-xs tabular-nums text-fg outline-none focus:border-primary" />
  );
}

function Color({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex items-center gap-2">
      <input type="color" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="h-7 w-10 cursor-pointer rounded border border-line bg-transparent" />
      <span className="text-2xs tabular-nums text-fg-muted">{value}</span>
    </div>
  );
}

function Editor({ t, total }: { t: Title; total: number }) {
  const l = titleLook(t);
  const [fonts, setFonts] = useState<{ family: string; bold: boolean }[]>([]);
  useEffect(() => { api.fonts().then(setFonts).catch(() => undefined); }, []);
  const set = (p: Partial<Title>, key?: string) =>
    editEdl((e) => ({ ...e, titles: e.titles.map((x) => (x.id === t.id ? { ...x, ...p } : x)) }), key ? `${key}-${t.id}` : undefined);
  const end = t.start + t.duration;
  return (
    <div className="space-y-1 rounded-xl border border-primary bg-panel2 p-3" aria-label="Text editor">
      <textarea
        aria-label="Text"
        rows={2}
        maxLength={200}
        value={t.text}
        onChange={(e) => set({ text: e.target.value }, "txt")}
        className="w-full resize-none rounded-lg border border-line bg-panel px-2 py-1.5 text-sm text-fg outline-none focus:border-primary"
      />
      <Field label="Font">
        <Select label="Font" className="w-40" value={l.font} options={(fonts.length ? fonts.map((f) => f.family) : [l.font]).map((f) => ({ value: f as FontFamily, label: f }))} onChange={(v) => set({ font: v })} />
      </Field>
      <Field label="Weight">
        <Segmented label="Font weight" value={l.weight} options={[{ value: "normal" as const, label: "Regular" }, { value: "bold" as const, label: "Bold" }]} onChange={(v) => set({ weight: v })} />
      </Field>
      <div className="py-1">
        <div className="mb-1 flex justify-between text-xs"><span>Size</span><span className="tabular-nums text-fg-muted">{Math.round(l.size * 100)}%</span></div>
        <Slider label="Text size" min={0.02} max={0.3} step={0.005} value={l.size} onChange={(v) => set({ size: v }, "size")} />
      </div>
      <Field label="Colour"><Color label="Text colour" value={l.color} onChange={(v) => set({ color: v }, "col")} /></Field>
      <div className="py-1">
        <div className="mb-1 flex justify-between text-xs"><span>Opacity</span><span className="tabular-nums text-fg-muted">{Math.round(l.opacity * 100)}%</span></div>
        <Slider label="Text opacity" min={0.05} max={1} step={0.05} value={l.opacity} onChange={(v) => set({ opacity: v }, "op")} />
      </div>
      <Field label="Alignment">
        <Segmented label="Text alignment" value={l.align} options={ALIGNS} onChange={(v) => set({ align: v })} />
      </Field>
      <div className="py-1">
        <div className="mb-1 flex justify-between text-xs"><span>Stroke</span><span className="tabular-nums text-fg-muted">{Math.round(l.strokeWidth * 100)}%</span></div>
        <Slider label="Stroke width" min={0} max={0.2} step={0.01} value={l.strokeWidth} onChange={(v) => set({ strokeWidth: v }, "sw")} />
      </div>
      {l.strokeWidth > 0 && <Field label="Stroke colour"><Color label="Stroke colour" value={l.strokeColor} onChange={(v) => set({ strokeColor: v }, "sc")} /></Field>}
      <Field label="Shadow"><Toggle label="Shadow" checked={l.shadow} onChange={(v) => set({ shadow: v })} /></Field>
      <Field label="Background"><Toggle label="Background" checked={!!l.background} onChange={(v) => set({ background: v ? "#000000" : "" })} /></Field>
      {l.background && (
        <>
          <Field label="Background colour"><Color label="Background colour" value={l.background} onChange={(v) => set({ background: v }, "bg")} /></Field>
          <div className="py-1">
            <div className="mb-1 flex justify-between text-xs"><span>Background opacity</span><span className="tabular-nums text-fg-muted">{Math.round(l.backgroundOpacity * 100)}%</span></div>
            <Slider label="Background opacity" min={0} max={1} step={0.05} value={l.backgroundOpacity} onChange={(v) => set({ backgroundOpacity: v }, "bo")} />
          </div>
        </>
      )}
      <Field label="Animation">
        <Segmented label="Text animation" value={l.animation} options={ANIMATIONS} onChange={(v) => set({ animation: v })} />
      </Field>
      <Field label="Rotation" hint="degrees">
        <Num label="Rotation" value={l.rotation} min={-180} max={180} step={1} onChange={(v) => set({ rotation: v }, "rot")} />
      </Field>
      <Field label="Position" hint="or drag it in the preview">
        <div className="flex gap-1">
          {PRESETS.map((p) => (
            <button key={p.value} onClick={() => set({ position: p.value, x: 0.5, y: p.y })}
              className={cx("rounded-lg border px-2 py-1 text-2xs", Math.abs((t.y ?? 0.5) - p.y) < 0.01 && Math.abs((t.x ?? 0.5) - 0.5) < 0.01 ? "border-primary text-primary" : "border-line text-fg-muted hover:text-fg")}>
              {p.label}
            </button>
          ))}
        </div>
      </Field>
      <Field label="Start" hint="seconds">
        <Num label="Start time" value={t.start} min={0} max={Math.max(0, total - 0.2)} step={0.1} onChange={(v) => set({ start: v }, "st")} />
      </Field>
      <Field label="End" hint={`of ${total.toFixed(1)}s`}>
        <Num label="End time" value={end} min={t.start + 0.2} max={Math.max(t.start + 0.2, total)} step={0.1} onChange={(v) => set({ duration: Math.max(0.2, Math.round((v - t.start) * 100) / 100) }, "en")} />
      </Field>
    </div>
  );
}

export function TextPanel() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const selectedId = useStore((s) => s.selectedTextId);
  const selectText = useStore((s) => s.selectText);
  const total = edl ? layout(edl).duration : 0;
  const selected = edl?.titles.find((t) => t.id === selectedId);

  const add = () => {
    if (!edl) return;
    const start = Math.min(useStore.getState().time, Math.max(0, total - 1));
    const t: Title = { id: uid("t"), text: "Your text", start: Math.round(start * 10) / 10, duration: Math.min(3, Math.max(0.5, total - start)), position: "center", ...TITLE_DEFAULTS, y: 0.5 };
    editEdl((e) => ({ ...e, titles: [...e.titles, t] }));
    selectText(t.id);
    useStore.getState().setPreviewMode("edit");
  };
  const duplicate = (t: Title) => {
    const copy: Title = { ...t, id: uid("t"), start: Math.min(t.start + 0.5, Math.max(0, total - 0.5)), x: Math.min(1, (t.x ?? 0.5) + 0.04), y: Math.min(1, (t.y ?? 0.5) + 0.04) };
    editEdl((e) => ({ ...e, titles: [...e.titles, copy] }));
    selectText(copy.id);
  };
  const remove = (id: string) => {
    editEdl((e) => ({ ...e, titles: e.titles.filter((x) => x.id !== id) }));
    if (selectedId === id) selectText(null);
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Text" subtitle="Add, style and place text on the video." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {!edl || !edl.clips.length ? (
          <Empty icon={<Type size={18} />} title="No timeline yet" text="Generate an edit first, then add text at the playhead." />
        ) : (
          <>
            <Button variant="primary" size="sm" className="w-full" icon={<Plus size={13} />} onClick={add}>Add text at playhead</Button>
            <p className="mt-1.5 text-2xs text-fg-faint">Click text in the preview to select it. Drag to move, use the corner to resize and the top dot to rotate. Arrow keys nudge it.</p>
            <ul className="mt-3 space-y-1.5">
              {edl.titles.map((t) => (
                <li key={t.id} className={cx("flex items-center gap-1 rounded-lg border px-2 py-1.5", selectedId === t.id ? "border-primary bg-primary-muted" : "border-line bg-panel2")}>
                  <button onClick={() => { selectText(t.id); useStore.getState().seek(t.start); }} className="min-w-0 flex-1 text-left" aria-pressed={selectedId === t.id}>
                    <span className="block truncate text-xs text-fg">{t.text || "(empty)"}</span>
                    <span className="text-2xs tabular-nums text-fg-faint">{t.start.toFixed(1)}s – {(t.start + t.duration).toFixed(1)}s</span>
                  </button>
                  <button aria-label="Duplicate text" onClick={() => duplicate(t)} className="flex h-7 w-7 items-center justify-center rounded text-fg-muted hover:bg-panel hover:text-fg"><Copy size={13} /></button>
                  <button aria-label="Delete text" onClick={() => remove(t.id)} className="flex h-7 w-7 items-center justify-center rounded text-fg-muted hover:bg-panel hover:text-danger"><Trash2 size={13} /></button>
                </li>
              ))}
              {!edl.titles.length && <li className="py-3 text-center text-2xs text-fg-faint">No text yet. Text appears on the timeline's Text track.</li>}
            </ul>
            {selected && <div className="mt-3"><Editor t={selected} total={total} /></div>}
          </>
        )}
      </div>
    </div>
  );
}

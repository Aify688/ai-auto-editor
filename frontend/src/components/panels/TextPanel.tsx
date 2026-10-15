import { Plus, Trash2, Type } from "lucide-react";
import { useState } from "react";
import { uid } from "../../lib/format";
import { layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import type { Title } from "../../types";
import { Button, Empty, PanelHeader, Segmented } from "../ui/controls";
import { editEdl } from "./shared";

const POSITIONS = [
  { value: "top" as const, label: "Top" },
  { value: "center" as const, label: "Center" },
  { value: "bottom" as const, label: "Bottom" },
];

function TitleRow({ t, max }: { t: Title; max: number }) {
  const set = (patch: Partial<Title>, coalesce?: string) =>
    editEdl((e) => ({ ...e, titles: e.titles.map((x) => (x.id === t.id ? { ...x, ...patch } : x)) }), coalesce);
  return (
    <div className="space-y-1.5 rounded-xl border border-line bg-panel2 p-2.5">
      <div className="flex gap-1">
        <input
          value={t.text}
          aria-label="Title text"
          maxLength={80}
          onChange={(e) => set({ text: e.target.value }, `title-text-${t.id}`)}
          className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-panel px-2 text-xs text-fg outline-none focus:border-primary"
        />
        <button aria-label="Delete title" onClick={() => editEdl((e) => ({ ...e, titles: e.titles.filter((x) => x.id !== t.id) }))} className="flex h-7 w-7 items-center justify-center rounded text-fg-muted hover:bg-panel hover:text-danger">
          <Trash2 size={13} />
        </button>
      </div>
      <div className="flex items-center gap-2 text-2xs text-fg-muted">
        <label className="flex items-center gap-1">
          Start
          <input type="number" min={0} max={max} step={0.1} value={t.start} aria-label="Start time"
            onChange={(e) => set({ start: Math.max(0, Math.min(max, Number(e.target.value) || 0)) }, `title-start-${t.id}`)}
            className="h-6 w-14 rounded border border-line bg-panel px-1 text-xs tabular-nums text-fg outline-none focus:border-primary" />
        </label>
        <label className="flex items-center gap-1">
          Length
          <input type="number" min={0.5} max={60} step={0.5} value={t.duration} aria-label="Duration"
            onChange={(e) => set({ duration: Math.max(0.5, Math.min(60, Number(e.target.value) || 3)) }, `title-dur-${t.id}`)}
            className="h-6 w-12 rounded border border-line bg-panel px-1 text-xs tabular-nums text-fg outline-none focus:border-primary" />
        </label>
      </div>
      <Segmented label="Position" value={t.position} options={POSITIONS} onChange={(v) => set({ position: v })} />
    </div>
  );
}

export function TextPanel() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const [text, setText] = useState("");
  const [position, setPosition] = useState<Title["position"]>("center");
  const total = edl ? layout(edl).duration : 0;

  const add = () => {
    if (!text.trim() || !edl) return;
    const start = Math.min(useStore.getState().time, Math.max(0, total - 0.5));
    editEdl((e) => ({ ...e, titles: [...e.titles, { id: uid("t"), text: text.trim(), start: Math.round(start * 10) / 10, duration: 3, position }] }));
    setText("");
    useStore.getState().setPreviewMode("edit");
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Text" subtitle="Titles drawn over your video." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        {!edl || !edl.clips.length ? (
          <Empty icon={<Type size={18} />} title="No timeline yet" text="Generate an edit first, then add titles at the playhead." />
        ) : (
          <>
            <div className="space-y-2 rounded-xl border border-line bg-panel2 p-2.5">
              <input
                value={text}
                maxLength={80}
                placeholder="Title text"
                aria-label="New title text"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && add()}
                className="h-9 w-full rounded-lg border border-line bg-panel px-2 text-sm text-fg outline-none placeholder:text-fg-faint focus:border-primary"
              />
              <Segmented label="Position" value={position} options={POSITIONS} onChange={setPosition} />
              <Button variant="primary" size="sm" className="w-full" icon={<Plus size={13} />} disabled={!text.trim()} onClick={add}>
                Add at playhead
              </Button>
            </div>
            <div className="mt-3 space-y-2">
              {edl.titles.map((t) => <TitleRow key={t.id} t={t} max={total} />)}
              {!edl.titles.length && <p className="text-center text-2xs text-fg-faint">Titles appear on the timeline's Text track.</p>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

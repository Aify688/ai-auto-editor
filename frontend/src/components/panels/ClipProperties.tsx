import { Scissors, SlidersHorizontal, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import { timelineActions } from "../timeline/Timeline";
import { Button, Empty } from "../ui/controls";

/** Properties of the selected timeline clip. Shows only fields the EDL really has. */
export function ClipProperties() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const selected = useStore((s) => s.selectedClipId);
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const laid = lay?.clips.find((c) => c.clip.id === selected);

  if (!laid)
    return <Empty icon={<SlidersHorizontal size={18} />} title="No clip selected" text="Select a clip on the timeline to see its details." />;

  const { clip } = laid;
  const source = media.find((m) => m.id === clip.mediaId);
  const rows: [string, string][] = [
    ["Source", source?.name ?? "–"],
    ["Starts at", fmtDuration(laid.outStart)],
    ["Length", fmtDuration(laid.outEnd - laid.outStart)],
    ["Source in", fmtDuration(clip.srcStart)],
    ["Source out", fmtDuration(clip.srcEnd)],
    ["Score", clip.score != null ? clip.score.toFixed(2) : "–"],
  ];
  return (
    <div className="space-y-4">
      <div>
        <div className="text-xs uppercase tracking-wide text-fg-faint">Clip {laid.index + 1}</div>
        <div className="truncate text-base font-semibold text-fg" title={clip.label}>{clip.label}</div>
      </div>
      <dl className="divide-y divide-line rounded-lg border border-line bg-panel2">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between gap-3 px-3 py-2">
            <dt className="text-xs text-fg-muted">{k}</dt>
            <dd className="min-w-0 truncate text-xs tabular-nums text-fg">{v}</dd>
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

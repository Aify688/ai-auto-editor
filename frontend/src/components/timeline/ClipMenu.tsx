import { Captions, Copy, Eraser, Scissors, Snowflake, Trash2, Gauge } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { startJob } from "../../hooks/useJobs";
import { deleteClip, duplicateClip, freezeFrameAt, setClipSpeed, SPEEDS } from "../../lib/edits";
import { layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import { cx } from "../ui/controls";
import { timelineActions } from "./Timeline";

export interface ClipMenuState {
  x: number;
  y: number;
  clipId: string;
}

function Item({ icon, label, onClick, danger, disabled }: { icon: ReactNode; label: string; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <button
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={cx(
        "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs hover:bg-white/10 disabled:opacity-40",
        danger ? "text-danger" : "text-fg",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

/** Right-click menu for a video clip on the timeline (CapCut style). */
export function ClipMenu({ menu, onClose }: { menu: ClipMenuState; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const edl = useStore((s) => s.doc?.edl ?? null);
  const media = useStore((s) => s.media);
  const updateDoc = useStore((s) => s.updateDoc);
  const clip = edl?.clips.find((c) => c.id === menu.clipId);

  useEffect(() => {
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", close, true);
    window.addEventListener("keydown", close);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("pointerdown", close, true);
      window.removeEventListener("keydown", close);
      window.removeEventListener("blur", onClose);
    };
  }, [onClose]);

  if (!edl || !clip) return null;
  const st = useStore.getState();
  const isVideo = media.find((m) => m.id === clip.mediaId)?.kind === "video";
  const run = (fn: () => void) => () => {
    fn();
    onClose();
  };
  const edit = (fn: (e: NonNullable<typeof edl>) => typeof edl) => updateDoc((d) => (d.edl ? { ...d, edl: fn(d.edl)! } : d));

  const freeze = () => {
    const lay = layout(edl);
    const dur = media.find((m) => m.id === clip.mediaId)?.duration ?? clip.srcEnd;
    const res = freezeFrameAt(edl, lay, st.time, clip.id, dur);
    if (!res) return st.toast("Move the playhead inside this clip to freeze that frame.");
    updateDoc((d) => ({ ...d, edl: res.edl }));
    st.selectClip(res.newId);
  };

  const width = 220;
  const left = Math.min(menu.x, window.innerWidth - width - 8);
  const top = Math.min(menu.y, window.innerHeight - 380);
  return (
    <div
      ref={ref}
      role="menu"
      aria-label="Clip actions"
      style={{ left, top, width }}
      className="fixed z-[60] rounded-lg border border-line bg-panel p-1 shadow-xl"
      onContextMenu={(e) => e.preventDefault()}
    >
      <Item icon={<Scissors size={13} />} label="Split at playhead" onClick={run(() => { st.selectClip(clip.id); timelineActions.split?.(); })} disabled={!!clip.freeze} />
      <Item icon={<Copy size={13} />} label="Duplicate" onClick={run(() => { const r = duplicateClip(edl, clip.id); if (r) { updateDoc((d) => ({ ...d, edl: r.edl })); st.selectClip(r.newId); } })} />
      <Item icon={<Snowflake size={13} />} label="Freeze frame" onClick={run(freeze)} disabled={!!clip.freeze} />
      {!clip.freeze && (
        <div className="px-2.5 pb-1.5 pt-1">
          <div className="mb-1 flex items-center gap-1.5 text-2xs text-fg-muted"><Gauge size={12} /> Speed</div>
          <div className="flex flex-wrap gap-1">
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={run(() => edit((e) => setClipSpeed(e, clip.id, s)))}
                className={cx("rounded-md border px-1.5 py-0.5 text-2xs tabular-nums", (clip.speed ?? 1) === s ? "border-primary text-fg" : "border-line text-fg-muted hover:text-fg")}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="my-1 h-px bg-line" />
      <Item icon={<Captions size={13} />} label="AI captions" onClick={run(() => { st.setNav("captions"); void startJob("transcribe"); })} />
      {isVideo && <Item icon={<Eraser size={13} />} label="Remove background…" onClick={run(() => st.selectClip(clip.id))} />}
      <div className="my-1 h-px bg-line" />
      <Item danger icon={<Trash2 size={13} />} label="Delete" onClick={run(() => edit((e) => deleteClip(e, clip.id)))} />
    </div>
  );
}

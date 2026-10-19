import { createContext, useContext, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode, type RefObject } from "react";
import { Repeat, Pencil } from "lucide-react";
import { retimeWords } from "../../lib/styles";
import { captionSpans, type CaptionSpan, type Layout } from "../../lib/layout";
import {
  assignLanes, audioLength, laneOthers, moveAudio, moveCaption, moveTitle, trimAudioEnd, trimAudioStart, trimCaptionEnd, trimCaptionStart,
  trimTitleEnd, trimTitleStart, withAudioClips, type ItemRef,
} from "../../lib/timelineOps";
import { useStore } from "../../store/project";
import type { AudioClip, Caption, Edl, Media, MusicLibraryTrack, Title } from "../../types";
import { cx } from "../ui/controls";
import { Waveform, usePeaks } from "./waveform";

export const LANE = { music: 40, captions: 30, textRow: 26 } as const;
const DRAG_PX = 4;

/** What the lanes need from the timeline: scale, snapping targets, and where to show the duration/snap feedback. */
export interface LaneEnv {
  pps: number;
  total: number;
  media: Record<string, Media>;
  library: MusicLibraryTrack[];
  points: (exclude?: ItemRef) => number[];
  mediaDur: (id: string) => number | undefined;
  setTip: (t: { x: number; y: number; text: string } | null) => void;
  setGuide: (t: number | null) => void;
}
export const LaneEnvCtx = createContext<LaneEnv>(null!);

type Result = { snapped: number | null; label: string; commit: () => void };

/**
 * Pointer gesture shared by every lane: press selects, moving more than a few pixels starts a drag, and the whole drag
 * is one undo step. `apply(deltaSeconds)` computes the result from the ORIGINAL item, so nothing accumulates.
 */
export function useItemDrag() {
  const env = useContext(LaneEnvCtx);
  return (e: RPointerEvent, spec: { select: () => void; apply: (delta: number) => Result | null; onClick?: () => void }) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    e.preventDefault();
    spec.select();
    const x0 = e.clientX;
    let dragging = false;
    const move = (ev: PointerEvent) => {
      if (!dragging && Math.abs(ev.clientX - x0) < DRAG_PX) return;
      dragging = true;
      const r = spec.apply((ev.clientX - x0) / env.pps);
      if (!r) return;
      r.commit();
      env.setTip({ x: ev.clientX, y: ev.clientY, text: r.label });
      env.setGuide(r.snapped);
    };
    const end = (cancel: boolean) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("keydown", key, true);
      if (cancel && dragging) spec.apply(0)?.commit();
      env.setTip(null);
      env.setGuide(null);
      if (!dragging) spec.onClick?.();
      const swallow = (ev: MouseEvent) => ev.stopPropagation();   // a drag must not also count as a click
      window.addEventListener("click", swallow, { capture: true, once: true });
      window.setTimeout(() => window.removeEventListener("click", swallow, { capture: true }), 0);
    };
    const up = () => end(false);
    const key = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") {
        ev.stopPropagation();
        end(true);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("keydown", key, true);
  };
}

const fmt = (s: number) => s.toFixed(2).replace(/\.?0+$/, "") + "s";
const dragKey = (kind: string, id: string) => `drag:${kind}:${id}:${Date.now()}`;

function Handles({ show, onLeft, onRight }: { show: boolean; onLeft: (e: RPointerEvent) => void; onRight: (e: RPointerEvent) => void }) {
  const grip = (side: "left" | "right", fn: (e: RPointerEvent) => void) => (
    <span
      aria-hidden
      onPointerDown={fn}
      className={cx("group/h absolute inset-y-0 z-20 flex w-2.5 cursor-ew-resize items-center justify-center", side === "left" ? "left-0" : "right-0")}
    >
      <span className={cx("h-3/5 w-1 rounded-full bg-white transition-opacity", show ? "opacity-90" : "opacity-0 group-hover/h:opacity-60")} />
    </span>
  );
  return <>{grip("left", onLeft)}{grip("right", onRight)}</>;
}

function InlineText({ value, onCommit, onCancel }: { value: string; onCommit: (v: string) => void; onCancel: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <input
      ref={ref}
      defaultValue={value}
      aria-label="Edit text"
      onPointerDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onBlur={(e) => onCommit(e.target.value)}
      onKeyDown={(e) => {
        e.stopPropagation();
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") onCancel();
      }}
      className="absolute inset-0 z-30 h-full w-full min-w-[120px] rounded-md border border-primary bg-app px-1.5 text-2xs text-fg outline-none"
    />
  );
}

/* ------------------------------------------------------------------ music / audio clips */
export function AudioLane({ edl, lay }: { edl: Edl; lay: Layout }) {
  const env = useContext(LaneEnvCtx);
  const drag = useItemDrag();
  const selected = useStore((s) => s.selectedAudioId);
  const selectAudio = useStore((s) => s.selectAudio);
  const updateDoc = useStore((s) => s.updateDoc);
  const clips = edl.audioClips ?? [];

  const base = (c: AudioClip, mode: "move" | "start" | "end", e: RPointerEvent) => {
    const key = dragKey("audio", c.id);
    const ctx = () => ({
      total: env.total, pps: env.pps, srcDur: env.mediaDur(c.mediaId), points: env.points({ kind: "audio", id: c.id }),
      others: laneOthers(clips, c.id, env.mediaDur, env.total),
    });
    const fn = mode === "move" ? moveAudio : mode === "start" ? trimAudioStart : trimAudioEnd;
    drag(e, {
      select: () => selectAudio(c.id),
      apply: (delta) => {
        const r = fn(c, delta, ctx());
        const len = r.clip.duration ?? 0;
        return {
          snapped: r.snapped,
          label: `${fmt(len)}  ·  ${fmt(r.clip.start)} – ${fmt(r.clip.start + len)}`,
          commit: () => updateDoc((d) => (d.edl ? { ...d, edl: withAudioClips(d.edl, d.edl.audioClips.map((x) => (x.id === c.id ? r.clip : x))) } : d), { coalesce: key }),
        };
      },
    });
  };

  return (
    <div className="relative" style={{ height: LANE.music }}>
      {clips.length === 0 && <div className="flex h-full items-center px-2 text-2xs text-fg-faint">No music. Add a track from Audio or Media, or let the AI pick one.</div>}
      {clips.map((c) => (
        <AudioClipView key={c.id} c={c} lay={lay} selected={selected === c.id} onBody={(e) => base(c, "move", e)} onLeft={(e) => base(c, "start", e)} onRight={(e) => base(c, "end", e)} />
      ))}
    </div>
  );
}

function AudioClipView({ c, lay, selected, onBody, onLeft, onRight }: {
  c: AudioClip; lay: Layout; selected: boolean; onBody: (e: RPointerEvent) => void; onLeft: (e: RPointerEvent) => void; onRight: (e: RPointerEvent) => void;
}) {
  const env = useContext(LaneEnvCtx);
  const m = env.media[c.mediaId];
  const lib = env.library.find((t) => t.id === c.mediaId);
  const peaks = usePeaks(m?.info.peaksUrl);
  const srcDur = env.mediaDur(c.mediaId);
  const len = audioLength(c, srcDur, lay.duration);
  const name = m?.name ?? lib?.title ?? "Audio";
  const w = Math.max(6, len * env.pps);
  return (
    <div
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`${c.kind === "music" ? "Music" : "Audio"} clip ${name}`}
      title={`${name}\nDrag to move · drag the edges to trim`}
      onPointerDown={onBody}
      className={cx("group absolute top-1 cursor-grab overflow-hidden rounded-md bg-clip-audio active:cursor-grabbing", selected ? "z-10 ring-2 ring-white" : "ring-1 ring-black/40 hover:ring-white/40")}
      style={{ left: c.start * env.pps, width: w, height: LANE.music - 8 }}
    >
      <div className="absolute inset-0">
        {peaks && srcDur ? (
          <Waveform peaks={peaks} step={m?.info.peakStep ?? 0.1} from={c.trimIn} seconds={len} pps={env.pps} loop={c.loop ? srcDur : undefined} color="#9FD8B9" />
        ) : (
          <div className="h-full w-full opacity-30" style={{ backgroundImage: "repeating-linear-gradient(90deg,#9FD8B9 0 2px,transparent 2px 6px)", maskImage: "linear-gradient(180deg,transparent 15%,#000 35%,#000 65%,transparent 85%)" }} />
        )}
      </div>
      {c.fadeIn > 0 && <div className="pointer-events-none absolute inset-y-0 left-0" style={{ width: c.fadeIn * env.pps, background: "linear-gradient(90deg,rgba(0,0,0,.55),transparent)" }} />}
      {c.fadeOut > 0 && <div className="pointer-events-none absolute inset-y-0 right-0" style={{ width: c.fadeOut * env.pps, background: "linear-gradient(270deg,rgba(0,0,0,.55),transparent)" }} />}
      <span className="pointer-events-none absolute left-2 top-0.5 flex max-w-[calc(100%-16px)] items-center gap-1 truncate rounded bg-black/40 px-1 text-2xs text-white">
        ♪ <span className="truncate">{name}</span>{c.loop && <Repeat size={9} aria-label="Looping" />}{c.duck ? " · ducked" : ""}
      </span>
      <Handles show={selected} onLeft={onLeft} onRight={onRight} />
    </div>
  );
}

/* ------------------------------------------------------------------ text overlays */
export function TextLane({ edl }: { edl: Edl }) {
  const env = useContext(LaneEnvCtx);
  const drag = useItemDrag();
  const selected = useStore((s) => s.selectedTextId);
  const selectText = useStore((s) => s.selectText);
  const updateDoc = useStore((s) => s.updateDoc);
  const [editing, setEditing] = useState<string | null>(null);
  const lanes = useMemo(() => assignLanes(edl.titles.map((t) => ({ id: t.id, start: t.start, end: t.start + t.duration }))), [edl.titles]);
  const rows = Math.max(1, ...[...lanes.values()].map((l) => l + 1));

  const begin = (t: Title, mode: "move" | "start" | "end", e: RPointerEvent) => {
    const key = dragKey("text", t.id);
    const fn = mode === "move" ? moveTitle : mode === "start" ? trimTitleStart : trimTitleEnd;
    drag(e, {
      select: () => selectText(t.id),
      onClick: () => { useStore.getState().setNav("text"); },
      apply: (delta) => {
        const r = fn(t, delta, { total: env.total, pps: env.pps, points: env.points({ kind: "text", id: t.id }) });
        return {
          snapped: r.snapped,
          label: `${fmt(r.title.duration)}  ·  ${fmt(r.title.start)} – ${fmt(r.title.start + r.title.duration)}`,
          commit: () => updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, titles: d.edl.titles.map((x) => (x.id === t.id ? r.title : x)) } } : d), { coalesce: key }),
        };
      },
    });
  };
  const setText = (t: Title, text: string) => {
    setEditing(null);
    if (text !== t.text) updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, titles: d.edl.titles.map((x) => (x.id === t.id ? { ...x, text } : x)) } } : d));
  };

  return (
    <div className="relative" style={{ height: rows * LANE.textRow }}>
      {edl.titles.map((t) => {
        const on = selected === t.id;
        return (
          <div
            key={t.id}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            aria-label={`Text ${t.text}`}
            title="Drag to move · drag the edges to change when it shows · double-click to edit"
            onPointerDown={(e) => begin(t, "move", e)}
            onDoubleClick={() => setEditing(t.id)}
            className={cx("absolute cursor-grab overflow-hidden rounded-md bg-clip-text px-2 text-left text-2xs text-white active:cursor-grabbing", on ? "z-10 ring-2 ring-white" : "ring-1 ring-black/40 hover:ring-white/40")}
            style={{ left: t.start * env.pps, width: Math.max(8, t.duration * env.pps), top: (lanes.get(t.id) ?? 0) * LANE.textRow + 1, height: LANE.textRow - 4 }}
          >
            <span className="block truncate leading-[20px]">T · {t.text}</span>
            <Handles show={on} onLeft={(e) => begin(t, "start", e)} onRight={(e) => begin(t, "end", e)} />
            {editing === t.id && <InlineText value={t.text} onCommit={(v) => setText(t, v)} onCancel={() => setEditing(null)} />}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ captions */
export function CaptionLane({ edl, lay }: { edl: Edl; lay: Layout }) {
  const env = useContext(LaneEnvCtx);
  const drag = useItemDrag();
  const selected = useStore((s) => s.selectedCaptionId);
  const selectCaption = useStore((s) => s.selectCaption);
  const updateDoc = useStore((s) => s.updateDoc);
  const [editing, setEditing] = useState<string | null>(null);
  const spans = useMemo(() => captionSpans(edl.captions, lay.clips), [edl.captions, lay]);

  const begin = (s: CaptionSpan, mode: "move" | "start" | "end", e: RPointerEvent) => {
    const key = dragKey("caption", s.caption.id);
    const others = spans.filter((x) => x.caption.id !== s.caption.id).map((x) => ({ start: x.outStart, end: x.outEnd }));
    const pts = env.points();
    drag(e, {
      select: () => selectCaption(s.caption.id),
      onClick: () => { useStore.getState().setNav("captions"); },
      apply: (delta) => {
        const ctx = { points: pts.filter((p) => !(Math.abs(p - s.outStart) < 1e-3 || Math.abs(p - s.outEnd) < 1e-3)), pps: env.pps, others };
        const r = mode === "move" ? moveCaption(s, delta, ctx) : mode === "start" ? trimCaptionStart(s, delta, ctx) : trimCaptionEnd(s, delta, ctx);
        const a = "start" in r ? (r as { start: number }).start : s.outStart;
        const b = "end" in r ? (r as { end: number }).end : mode === "move" ? a + (s.outEnd - s.outStart) : s.outEnd;
        return {
          snapped: r.snapped,
          label: `${fmt(b - a)}  ·  ${fmt(a)} – ${fmt(b)}`,
          commit: () => updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, captions: d.edl.captions.map((x) => (x.id === s.caption.id ? r.caption : x)) } } : d), { coalesce: key }),
        };
      },
    });
  };
  const setText = (c: Caption, text: string) => {
    setEditing(null);
    if (text === c.text) return;
    updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, captions: d.edl.captions.map((x) => (x.id === c.id ? { ...x, text, words: x.words?.length ? retimeWords(text, x.srcStart, x.srcEnd) : null } : x)) } } : d));
  };

  return (
    <div className="relative" style={{ height: LANE.captions }}>
      {spans.map((s, i) => {
        const on = selected === s.caption.id;
        return (
          <div
            key={`${s.caption.id}-${i}`}
            role="button"
            tabIndex={0}
            aria-pressed={on}
            aria-label={`Caption ${s.caption.text}`}
            title={`${s.caption.text}\nDrag to retime · double-click to edit${s.caption.manual ? "\nTiming set by hand (Reset in Captions)" : ""}`}
            onPointerDown={(e) => begin(s, "move", e)}
            onDoubleClick={() => setEditing(s.caption.id)}
            className={cx("absolute top-1 cursor-grab overflow-hidden rounded-md px-2 text-left text-2xs text-white active:cursor-grabbing",
              edl.burnCaptions ? "bg-clip-caption" : "bg-clip-caption/40", on ? "z-10 ring-2 ring-white" : "ring-1 ring-black/40 hover:ring-white/40")}
            style={{ left: s.outStart * env.pps, width: Math.max(8, (s.outEnd - s.outStart) * env.pps), height: LANE.captions - 8 }}
          >
            <span className="flex items-center gap-1 leading-[22px]">
              {s.caption.manual && <Pencil size={9} aria-label="Timing set by hand" className="shrink-0 opacity-80" />}
              <span className="truncate">{s.caption.text}</span>
            </span>
            <Handles show={on} onLeft={(e) => begin(s, "start", e)} onRight={(e) => begin(s, "end", e)} />
            {editing === s.caption.id && <InlineText value={s.caption.text} onCommit={(v) => setText(s.caption, v)} onCancel={() => setEditing(null)} />}
          </div>
        );
      })}
    </div>
  );
}

/** Floating duration/position readout while dragging, and the snap line. */
export function DragFeedback({ tip, guide, pps, height }: { tip: { x: number; y: number; text: string } | null; guide: number | null; pps: number; height: number }): ReactNode {
  return (
    <>
      {guide !== null && <div className="pointer-events-none absolute top-0 z-40 w-px bg-primary" style={{ left: guide * pps, height }} aria-hidden />}
      {tip && (
        <div role="status" className="pointer-events-none fixed z-[70] rounded-md border border-line bg-raise px-2 py-1 text-2xs tabular-nums text-fg shadow-lg" style={{ left: tip.x + 14, top: tip.y - 34 }}>
          {tip.text}
        </div>
      )}
    </>
  );
}

export type { RefObject };

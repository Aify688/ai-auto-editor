import {
  AudioLines, Captions, Copy, Film, Flag, Maximize2, Music, Redo2, Scissors, Sparkles, Trash2, Type, Undo2, ZoomIn, ZoomOut,
} from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { deleteClip, displayBounds, moveClip, setFreezeHold, splitAt, trimClip } from "../../lib/edits";
import { clamp, fmtTime } from "../../lib/format";
import { ClipMenu, type ClipMenuState } from "./ClipMenu";
import { captionSpans, clipDuration, clipRate, layout, type Layout } from "../../lib/layout";
import {
  assignLanes, duplicateAudio, duplicateCaption, duplicateTitle, laneOthers, moveAudio, moveCaption, moveTitle, snapPoints, splitAudio,
  splitCaption, splitTitle, toggleMarker, withAudioClips, type ItemRef,
} from "../../lib/timelineOps";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { Edl, Media, MusicLibraryTrack } from "../../types";
import { IconButton, cx } from "../ui/controls";
import { AudioLane, CaptionLane, DragFeedback, LANE, LaneEnvCtx, TextLane, type LaneEnv } from "./lanes";
import { Waveform, usePeaks } from "./waveform";

const HEADER_W = 92;
const RULER_H = 24;
const TRACK = { video: 58, audio: 42, music: LANE.music, captions: LANE.captions, textRow: LANE.textRow };
const MIN_PPS = 8;
const MAX_PPS = 320;
const HEIGHT_KEY = "frameflow.timelineHeight";

function Filmstrip({ m, from, seconds, pps, height, rate = 1 }: { m: Media; from: number; seconds: number; pps: number; height: number; rate?: number }) {
  const sp = m.info.sprite;
  if (!sp || !m.info.spriteUrl) return null;
  const scale = height / sp.tileH;
  const tw = sp.tileW * scale;
  const width = seconds * pps;
  const n = Math.min(400, Math.ceil(width / tw));
  return (
    <div className="absolute inset-0 flex overflow-hidden opacity-80">
      {Array.from({ length: n }, (_, k) => {
        const t = from + ((k * tw + tw / 2) / pps) * rate;
        const idx = clamp(Math.floor(t / sp.step), 0, sp.count - 1);
        return (
          <div
            key={k}
            className="h-full shrink-0"
            style={{
              width: tw,
              backgroundImage: `url(${m.info.spriteUrl})`,
              backgroundSize: `${sp.count * tw}px ${height}px`,
              backgroundPosition: `${-idx * tw}px 0`,
            }}
          />
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ playhead (re-renders on every frame) */
const Playhead = memo(function Playhead({ pps, height, onDrag }: { pps: number; height: number; onDrag: (e: React.PointerEvent) => void }) {
  const time = useStore((s) => s.time);
  return (
    <div className="pointer-events-none absolute top-0 z-30" style={{ left: time * pps, height }}>
      <div
        onPointerDown={onDrag}
        className="pointer-events-auto absolute -left-[6px] top-0 h-3 w-3 cursor-ew-resize rounded-b-md bg-fg"
        style={{ clipPath: "polygon(0 0,100% 0,100% 55%,50% 100%,0 55%)" }}
      />
      <div className="absolute left-[-0.5px] top-0 h-full w-px bg-fg" />
    </div>
  );
});

function TimeReadout({ duration }: { duration: number }) {
  const time = useStore((s) => s.time);
  return (
    <span className="text-xs tabular-nums">
      <span className="text-fg">{fmtTime(time, true)}</span>
      <span className="text-fg-faint"> / {fmtTime(duration, true)}</span>
    </span>
  );
}

function Ruler({ pps, width, duration, markers }: { pps: number; width: number; duration: number; markers: number[] }) {
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120];
  const major = steps.find((s) => s * pps >= 70) ?? 120;
  const minor = major / 5;
  const ticks = [];
  for (let k = 0; k * minor * pps <= width; k++) {
    const t = k * minor; // integer stepping avoids float drift (1.9999 -> "00:01")
    const isMajor = k % 5 === 0;
    ticks.push(
      <div key={t.toFixed(3)} className="absolute bottom-0" style={{ left: t * pps }}>
        <div className={cx("w-px", isMajor ? "h-2.5 bg-[#59606E]" : "h-1.5 bg-line")} />
        {isMajor && <span className="absolute bottom-3 left-1 text-2xs tabular-nums text-fg-faint">{major < 1 ? fmtTime(t, true) : fmtTime(t)}</span>}
      </div>,
    );
  }
  return (
    <div className="relative" style={{ height: RULER_H, width }}>
      {ticks}
      <div className="absolute bottom-0 h-px bg-line" style={{ width: Math.max(0, duration * pps) }} />
      {markers.map((m) => (
        <button
          key={m}
          aria-label={`Marker at ${fmtTime(m, true)}`}
          title={`Marker ${fmtTime(m, true)} (M at the playhead removes it)`}
          onPointerDown={(e) => { e.stopPropagation(); useStore.getState().seek(m); }}
          className="absolute top-0 z-20 -translate-x-1/2 text-warn hover:brightness-125"
          style={{ left: m * pps }}
        >
          <Flag size={11} fill="currentColor" />
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ video track */
function VideoTrack({ edl, lay, pps, media }: { edl: Edl; lay: Layout; pps: number; media: Record<string, Media> }) {
  const selectedId = useStore((s) => s.selectedClipId);
  const updateDoc = useStore((s) => s.updateDoc);
  const selectClip = useStore((s) => s.selectClip);
  const bounds = useMemo(() => displayBounds(lay), [lay]);
  const [drag, setDrag] = useState<{ from: number; x: number; to: number } | null>(null);
  const [menu, setMenu] = useState<ClipMenuState | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);

  const dropIndex = (x: number) => {
    let to = bounds.length;
    for (let i = 0; i < bounds.length; i++) {
      if (x < ((bounds[i].start + bounds[i].end) / 2) * pps) {
        to = i;
        break;
      }
    }
    return to;
  };

  const onClipDown = (e: React.PointerEvent, index: number) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    const startX = e.clientX;
    const rect = trackRef.current!.getBoundingClientRect();
    let moved = false;
    const move = (ev: PointerEvent) => {
      if (!moved && Math.abs(ev.clientX - startX) < 4) return;
      moved = true;
      const x = ev.clientX - rect.left;
      setDrag({ from: index, x, to: dropIndex(x) });
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setDrag(null);
      if (!moved) {
        selectClip(edl.clips[index].id);
        return;
      }
      const to = dropIndex(ev.clientX - rect.left);
      updateDoc((d) => (d.edl ? { ...d, edl: moveClip(d.edl, index, to) } : d));
      selectClip(edl.clips[index].id);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const onTrim = (e: React.PointerEvent, clipId: string, edge: "start" | "end") => {
    e.stopPropagation();
    e.preventDefault();
    const clip = edl.clips.find((c) => c.id === clipId)!;
    const dur = media[clip.mediaId]?.duration ?? clip.srcEnd;
    const startX = e.clientX;
    const v0 = edge === "start" ? clip.srcStart : clip.srcEnd;
    const rate = clipRate(clip);
    const hold0 = clip.freeze ?? 0;
    const key = `drag:trim:${clipId}:${Date.now()}`;
    selectClip(clipId);
    const move = (ev: PointerEvent) => {
      const dx = (ev.clientX - startX) / pps;
      if (clip.freeze) {
        // a freeze frame has no source range to trim: its handles stretch or shrink the hold time
        updateDoc((d) => (d.edl ? { ...d, edl: setFreezeHold(d.edl, clipId, hold0 + (edge === "end" ? dx : -dx)) } : d), { coalesce: key });
        return;
      }
      const value = v0 + dx * rate;
      updateDoc((d) => (d.edl ? { ...d, edl: trimClip(d.edl, clipId, edge, value, dur) } : d), { coalesce: key });
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={trackRef} className="relative" style={{ height: TRACK.video }}>
      {lay.clips.map((lc, i) => {
        const b = bounds[i];
        const m = media[lc.clip.mediaId];
        const left = b.start * pps;
        const width = Math.max(2, (b.end - b.start) * pps);
        const sel = selectedId === lc.clip.id;
        return (
          <div
            key={lc.clip.id}
            onPointerDown={(e) => onClipDown(e, i)}
            onContextMenu={(e) => {
              e.preventDefault();
              selectClip(lc.clip.id);
              setMenu({ x: e.clientX, y: e.clientY, clipId: lc.clip.id });
            }}
            title={`${lc.clip.label || m?.name} · ${clipDuration(lc.clip).toFixed(2)}s${lc.clip.freeze ? " (freeze frame)" : lc.clip.speed && lc.clip.speed !== 1 ? ` at ${lc.clip.speed}x` : ""} (source ${lc.clip.srcStart.toFixed(2)}–${lc.clip.srcEnd.toFixed(2)}s)`}
            className={cx(
              "group absolute top-1 cursor-grab overflow-hidden rounded-md bg-clip-video active:cursor-grabbing",
              sel ? "z-10 ring-2 ring-white" : "ring-1 ring-black/40 hover:ring-white/40",
              drag?.from === i && "opacity-40",
            )}
            style={{ left: left + 0.5, width: width - 1, height: TRACK.video - 8 }}
          >
            {m && <Filmstrip m={m} from={lc.clip.srcStart + (b.start - lc.outStart) * clipRate(lc.clip)} seconds={b.end - b.start} rate={clipRate(lc.clip)} pps={pps} height={TRACK.video - 8} />}
            <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-1 bg-gradient-to-b from-black/70 to-transparent px-1.5 pb-2 pt-0.5">
              <span className="truncate text-2xs font-medium text-white">{lc.clip.label || m?.name}</span>
              {width > 70 && (
                <span className="shrink-0 text-2xs tabular-nums text-white/80">
                  {lc.clip.freeze ? "❄ " : lc.clip.speed && lc.clip.speed !== 1 ? `${lc.clip.speed}x · ` : ""}
                  {clipDuration(lc.clip).toFixed(1)}s
                </span>
              )}
            </div>
            <div
              onPointerDown={(e) => onTrim(e, lc.clip.id, "start")}
              className={cx("absolute inset-y-0 left-0 w-1.5 cursor-ew-resize bg-white/80", sel ? "opacity-100" : "opacity-0 group-hover:opacity-70")}
              aria-label="Trim start"
            />
            <div
              onPointerDown={(e) => onTrim(e, lc.clip.id, "end")}
              className={cx("absolute inset-y-0 right-0 w-1.5 cursor-ew-resize bg-white/80", sel ? "opacity-100" : "opacity-0 group-hover:opacity-70")}
              aria-label="Trim end"
            />
          </div>
        );
      })}
      {menu && <ClipMenu menu={menu} onClose={() => setMenu(null)} />}
      {bounds.map((b, i) =>
        b.transitionBefore ? (
          <div
            key={`t${i}`}
            title={`${edl.transition?.type} · ${lay.transition}s`}
            className="pointer-events-none absolute top-1/2 z-20 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rotate-45 rounded-[2px] border border-white/70 bg-[#2B3A55]"
            style={{ left: b.start * pps }}
          />
        ) : null,
      )}
      {drag && (
        <div className="pointer-events-none absolute top-0 z-40 h-full w-0.5 bg-primary" style={{ left: (bounds[drag.to]?.start ?? lay.duration) * pps }} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ audio, captions, text tracks */
function AudioTrack({ lay, pps, media }: { lay: Layout; pps: number; media: Record<string, Media> }) {
  const bounds = useMemo(() => displayBounds(lay), [lay]);
  return (
    <div className="relative" style={{ height: TRACK.audio }}>
      {lay.clips.map((lc, i) => {
        const m = media[lc.clip.mediaId];
        const b = bounds[i];
        return (
          <ClipAudio key={lc.clip.id} m={m} from={lc.clip.srcStart + (b.start - lc.outStart) * clipRate(lc.clip)} seconds={b.end - b.start} left={b.start * pps} pps={pps} />
        );
      })}
    </div>
  );
}

function ClipAudio({ m, from, seconds, left, pps }: { m?: Media; from: number; seconds: number; left: number; pps: number }) {
  const peaks = usePeaks(m?.hasAudio ? m.info.peaksUrl : undefined);
  return (
    <div className="absolute top-1 overflow-hidden rounded-md bg-clip-audio/60" style={{ left: left + 0.5, width: Math.max(2, seconds * pps - 1), height: TRACK.audio - 8 }}>
      {m?.hasAudio ? (
        peaks && <Waveform peaks={peaks} step={m.info.peakStep ?? 0.1} from={from} seconds={seconds} pps={pps} color="#9FD8B9" />
      ) : (
        <span className="absolute left-1.5 top-1 text-2xs text-white/50">No audio</span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ main */
export function Timeline() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const mediaList = useStore((s) => s.media);
  const selectedId = useStore((s) => s.selectedClipId);
  const hasSelection = useStore((s) => !!(s.selectedClipId || s.selectedAudioId || s.selectedTextId || s.selectedCaptionId));
  const canUndo = useStore((s) => s.past.length > 0);
  const canRedo = useStore((s) => s.future.length > 0);
  const { undo, redo, updateDoc, selectClip } = useStore.getState();
  const media = useMemo(() => Object.fromEntries(mediaList.map((m) => [m.id, m])), [mediaList]);
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [viewW, setViewW] = useState(800);
  const [pps, setPps] = useState<number | null>(null);
  const [height, setHeight] = useState(() => {
    try {
      return Number(localStorage.getItem(HEIGHT_KEY)) || 300;
    } catch {
      return 250;
    }
  });

  const duration = lay?.duration ?? 0;
  const fitPps = clamp((viewW - 40) / Math.max(5, duration), MIN_PPS, MAX_PPS);
  const zoom = pps ?? fitPps;
  const contentW = Math.max(viewW - HEADER_W, (duration + 4) * zoom);
  const textRows = useMemo(() => {
    const lanes = assignLanes((edl?.titles ?? []).map((t) => ({ id: t.id, start: t.start, end: t.start + t.duration })));
    return Math.max(1, ...[...lanes.values()].map((l) => l + 1));
  }, [edl?.titles]);
  const tracksH = RULER_H + TRACK.video + TRACK.audio + TRACK.music + TRACK.captions + textRows * TRACK.textRow + 4;
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const [guide, setGuide] = useState<number | null>(null);
  const [library, setLibrary] = useState<MusicLibraryTrack[]>([]);
  useEffect(() => { api.musicLibrary().then(setLibrary).catch(() => undefined); }, []);
  const mediaDur = useCallback((id: string) => media[id]?.duration ?? library.find((t) => t.id === id)?.duration ?? undefined, [media, library]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setViewW(e.contentRect.width + HEADER_W));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // keep the playhead in view while playing
  useEffect(
    () =>
      useStore.subscribe((s, prev) => {
        const el = scrollRef.current;
        if (!el || !s.playing || s.time === prev.time) return;
        const x = s.time * zoom;
        if (x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - 80;
        else if (x < el.scrollLeft) el.scrollLeft = Math.max(0, x - 40);
      }),
    [zoom],
  );

  const timeFromEvent = useCallback(
    (clientX: number) => {
      const el = scrollRef.current!;
      const x = clientX - el.getBoundingClientRect().left + el.scrollLeft;
      return clamp(x / zoom, 0, duration);
    },
    [zoom, duration],
  );

  const scrub = (e: React.PointerEvent) => {
    if (e.button !== 0 || !lay) return;
    e.preventDefault();
    const s = useStore.getState();
    if (s.previewMode !== "edit") s.setPreviewMode("edit");
    s.seek(timeFromEvent(e.clientX));
    const move = (ev: PointerEvent) => useStore.getState().seek(timeFromEvent(ev.clientX));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const env: LaneEnv | null = useMemo(
    () => (edl && lay ? {
      pps: zoom, total: lay.duration, media, library, mediaDur,
      points: (exclude?: ItemRef) => snapPoints(edl, lay, useStore.getState().time, mediaDur, exclude),
      setTip, setGuide,
    } : null),
    [edl, lay, zoom, media, library, mediaDur],
  );

  /** Whatever is selected: video clip, music/audio clip, text or caption. */
  const selection = () => {
    const st = useStore.getState();
    if (st.selectedAudioId) return { kind: "audio" as const, id: st.selectedAudioId };
    if (st.selectedTextId) return { kind: "text" as const, id: st.selectedTextId };
    if (st.selectedCaptionId) return { kind: "caption" as const, id: st.selectedCaptionId };
    if (st.selectedClipId) return { kind: "clip" as const, id: st.selectedClipId };
    return null;
  };
  const setEdl = (fn: (e: Edl) => Edl) => updateDoc((d) => (d.edl ? { ...d, edl: fn(d.edl) } : d));
  const toast = (m: string) => useStore.getState().toast(m);

  const split = () => {
    if (!edl || !lay) return;
    const t = useStore.getState().time;
    const sel = selection();
    if (sel?.kind === "audio") {
      const c = edl.audioClips.find((x) => x.id === sel.id)!;
      const parts = splitAudio(c, t, { srcDur: mediaDur(c.mediaId), total: lay.duration });
      if (!parts) return toast("Move the playhead inside the audio clip (at least 0.2 s from its edges) to split it.");
      setEdl((e) => withAudioClips(e, e.audioClips.flatMap((x) => (x.id === c.id ? parts : [x]))));
      useStore.getState().selectAudio(parts[1].id);
      return;
    }
    if (sel?.kind === "text") {
      const tt = edl.titles.find((x) => x.id === sel.id)!;
      const parts = splitTitle(tt, t);
      if (!parts) return toast("Move the playhead inside the text (at least 0.2 s from its edges) to split it.");
      setEdl((e) => ({ ...e, titles: e.titles.flatMap((x) => (x.id === tt.id ? parts : [x])) }));
      useStore.getState().selectText(parts[1].id);
      return;
    }
    if (sel?.kind === "caption") {
      const sp = captionSpans(edl.captions, lay.clips).find((x) => x.caption.id === sel.id && t >= x.outStart && t <= x.outEnd);
      const parts = sp && splitCaption(sp, t);
      if (!parts) return toast("Move the playhead inside the caption to split it.");
      setEdl((e) => ({ ...e, captions: e.captions.flatMap((x) => (x.id === sel.id ? parts : [x])) }));
      useStore.getState().selectCaption(parts[1].id);
      return;
    }
    const res = splitAt(edl, lay, t, selectedId);
    if (!res) return toast("Move the playhead inside a clip (at least 0.3 s from its edges) to split.");
    updateDoc((d) => ({ ...d, edl: res.edl }));
    selectClip(res.newId);
  };
  const remove = () => {
    if (!edl) return;
    const sel = selection();
    if (!sel) return;
    const st = useStore.getState();
    if (sel.kind === "audio") { setEdl((e) => withAudioClips(e, e.audioClips.filter((x) => x.id !== sel.id))); st.selectAudio(null); }
    else if (sel.kind === "text") { setEdl((e) => ({ ...e, titles: e.titles.filter((x) => x.id !== sel.id) })); st.selectText(null); }
    else if (sel.kind === "caption") { setEdl((e) => ({ ...e, captions: e.captions.filter((x) => x.id !== sel.id) })); st.selectCaption(null); }
    else { updateDoc((d) => (d.edl ? { ...d, edl: deleteClip(d.edl, sel.id) } : d)); selectClip(null); }
  };
  const duplicate = () => {
    if (!edl || !lay) return;
    const sel = selection();
    const st = useStore.getState();
    if (sel?.kind === "audio") {
      const c = edl.audioClips.find((x) => x.id === sel.id)!;
      const copy = duplicateAudio(c, { srcDur: mediaDur(c.mediaId), total: lay.duration, others: laneOthers(edl.audioClips, c.id, mediaDur, lay.duration) });
      if (!copy) return toast("There is no free space after this audio clip for a copy.");
      setEdl((e) => withAudioClips(e, [...e.audioClips, copy]));
      st.selectAudio(copy.id);
    } else if (sel?.kind === "text") {
      const copy = duplicateTitle(edl.titles.find((x) => x.id === sel.id)!, lay.duration);
      setEdl((e) => ({ ...e, titles: [...e.titles, copy] }));
      st.selectText(copy.id);
    } else if (sel?.kind === "caption") {
      const spans = captionSpans(edl.captions, lay.clips);
      const sp = spans.find((x) => x.caption.id === sel.id);
      const copy = sp && duplicateCaption(sp, spans.filter((x) => x.caption.id !== sel.id).map((x) => ({ start: x.outStart, end: x.outEnd })));
      if (!copy) return toast("There is no free space after this caption for a copy.");
      setEdl((e) => ({ ...e, captions: [...e.captions, copy] }));
      st.selectCaption(copy.id);
    } else toast("Select an audio clip, text or caption to duplicate it.");
  };
  /** Alt+arrows: move the selected audio/text/caption by 0.1 s (1 s with Shift) without the mouse. */
  const nudge = (dir: -1 | 1, big: boolean) => {
    if (!edl || !lay) return;
    const sel = selection();
    const delta = dir * (big ? 1 : 0.1);
    const none: number[] = [];
    if (sel?.kind === "audio") {
      const c = edl.audioClips.find((x) => x.id === sel.id)!;
      const r = moveAudio(c, delta, { total: lay.duration, pps: zoom, points: none, srcDur: mediaDur(c.mediaId), others: laneOthers(edl.audioClips, c.id, mediaDur, lay.duration) });
      setEdl((e) => withAudioClips(e, e.audioClips.map((x) => (x.id === c.id ? r.clip : x))));
    } else if (sel?.kind === "text") {
      const r = moveTitle(edl.titles.find((x) => x.id === sel.id)!, delta, { total: lay.duration, points: none, pps: zoom });
      setEdl((e) => ({ ...e, titles: e.titles.map((x) => (x.id === sel.id ? r.title : x)) }));
    } else if (sel?.kind === "caption") {
      const spans = captionSpans(edl.captions, lay.clips);
      const sp = spans.find((x) => x.caption.id === sel.id);
      if (!sp) return;
      const r = moveCaption(sp, delta, { points: none, pps: zoom, others: spans.filter((x) => x.caption.id !== sel.id).map((x) => ({ start: x.outStart, end: x.outEnd })) });
      setEdl((e) => ({ ...e, captions: e.captions.map((x) => (x.id === sel.id ? r.caption : x)) }));
    }
  };
  const marker = () => setEdl((e) => ({ ...e, markers: toggleMarker(e.markers ?? [], useStore.getState().time) }));

  const startResize = (e: React.PointerEvent) => {
    e.preventDefault();
    const y0 = e.clientY;
    const h0 = height;
    const move = (ev: PointerEvent) => setHeight(clamp(h0 - (ev.clientY - y0), 150, Math.round(window.innerHeight * 0.6)));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      setHeight((h) => {
        try {
          localStorage.setItem(HEIGHT_KEY, String(h));
        } catch {
          /* ignore */
        }
        return h;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // expose split/delete to keyboard shortcuts
  useEffect(() => {
    timelineActions.split = split;
    timelineActions.remove = remove;
    timelineActions.duplicate = duplicate;
    timelineActions.nudge = nudge;
    timelineActions.marker = marker;
  });

  const headers = [
    { icon: Film, label: "Video", h: TRACK.video },
    { icon: AudioLines, label: "Audio", h: TRACK.audio },
    { icon: Music, label: "Music", h: TRACK.music },
    { icon: Captions, label: "Captions", h: TRACK.captions },
    { icon: Type, label: "Text", h: textRows * TRACK.textRow },
  ];

  return (
    <section className="relative flex shrink-0 flex-col border-t border-line bg-panel" style={{ height }} aria-label="Timeline">
      <div onPointerDown={startResize} className="absolute -top-1 left-0 right-0 z-40 h-2 cursor-ns-resize" title="Drag to resize" />
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-line px-3">
        <div className="flex items-center gap-0.5">
          <IconButton label="Undo (⌘Z)" onClick={undo} disabled={!canUndo}><Undo2 size={15} /></IconButton>
          <IconButton label="Redo (⇧⌘Z)" onClick={redo} disabled={!canRedo}><Redo2 size={15} /></IconButton>
          <div className="mx-1.5 h-4 w-px bg-line" />
          <IconButton label="Split at playhead (S)" onClick={split} disabled={!edl?.clips.length}><Scissors size={15} /></IconButton>
          <IconButton label="Duplicate (⌘D)" onClick={duplicate} disabled={!hasSelection}><Copy size={15} /></IconButton>
          <IconButton label="Delete (Del)" onClick={remove} disabled={!hasSelection}><Trash2 size={15} /></IconButton>
          <IconButton label="Add or remove a marker at the playhead (M)" onClick={marker} disabled={!edl?.clips.length}><Flag size={15} /></IconButton>
        </div>
        <TimeReadout duration={duration} />
        <div className="flex items-center gap-1">
          <IconButton label="Zoom out" onClick={() => setPps(clamp(zoom / 1.5, MIN_PPS, MAX_PPS))}><ZoomOut size={15} /></IconButton>
          <input
            type="range"
            aria-label="Timeline zoom"
            className="ff-range w-24"
            min={Math.log(MIN_PPS)}
            max={Math.log(MAX_PPS)}
            step={0.01}
            value={Math.log(zoom)}
            onChange={(e) => setPps(Math.exp(Number(e.target.value)))}
            style={{ background: `linear-gradient(to right, #A3ABB9 ${((Math.log(zoom) - Math.log(MIN_PPS)) / (Math.log(MAX_PPS) - Math.log(MIN_PPS))) * 100}%, #383E49 0)` }}
          />
          <IconButton label="Zoom in" onClick={() => setPps(clamp(zoom * 1.5, MIN_PPS, MAX_PPS))}><ZoomIn size={15} /></IconButton>
          <IconButton label="Fit to view" onClick={() => setPps(null)}><Maximize2 size={14} /></IconButton>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
        <div className="shrink-0 border-r border-line bg-panel" style={{ width: HEADER_W }}>
          <div style={{ height: RULER_H }} />
          {headers.map(({ icon: Icon, label, h }) => (
            <div key={label} className="flex items-center gap-1.5 border-t border-line/50 px-2.5 text-2xs text-fg-muted" style={{ height: h }}>
              <Icon size={13} /> {label}
            </div>
          ))}
        </div>
        <div
          ref={scrollRef}
          className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden"
          style={{ height: edl?.clips.length ? tracksH : "100%" }}
          onWheel={(e) => {
            if (!(e.ctrlKey || e.metaKey)) return;
            e.preventDefault();
            setPps(clamp(zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), MIN_PPS, MAX_PPS));
          }}
        >
          {!edl || !lay || edl.clips.length === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-fg-muted">
              <Sparkles size={14} className="text-primary" />
              Generate an AI video to build the timeline, or add clips from Media with +.
            </div>
          ) : (
            <LaneEnvCtx.Provider value={env!}>
              <div className="relative" style={{ width: contentW, height: tracksH }} onPointerDown={(e) => { scrub(e); useStore.getState().selectAudio(null); useStore.getState().selectCaption(null); }}>
                <div className="cursor-pointer"><Ruler pps={zoom} width={contentW} duration={duration} markers={edl.markers ?? []} /></div>
                <div className="border-t border-line/50"><VideoTrack edl={edl} lay={lay} pps={zoom} media={media} /></div>
                <div className="border-t border-line/50"><AudioTrack lay={lay} pps={zoom} media={media} /></div>
                <div className="border-t border-line/50"><AudioLane edl={edl} lay={lay} /></div>
                <div className="border-t border-line/50">
                  {edl.captions.length > 0 ? <CaptionLane edl={edl} lay={lay} /> : (
                    <div className="flex items-center px-2 text-2xs text-fg-faint" style={{ height: TRACK.captions }}>No captions · turn on Automatic captions or use the Captions panel</div>
                  )}
                </div>
                <div className="border-t border-line/50">
                  {edl.titles.length > 0 ? <TextLane edl={edl} /> : (
                    <div className="flex items-center px-2 text-2xs text-fg-faint" style={{ height: TRACK.textRow }}>No text · add some in the Text panel</div>
                  )}
                </div>
                <Playhead pps={zoom} height={tracksH} onDrag={(e) => { e.stopPropagation(); scrub(e); }} />
                <DragFeedback tip={tip} guide={guide} pps={zoom} height={tracksH} />
              </div>
            </LaneEnvCtx.Provider>
          )}
        </div>
      </div>
    </section>
  );
}

export const timelineActions: {
  split?: () => void;
  remove?: () => void;
  duplicate?: () => void;
  nudge?: (dir: -1 | 1, big: boolean) => void;
  marker?: () => void;
} = {};

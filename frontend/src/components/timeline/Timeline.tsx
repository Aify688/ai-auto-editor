import {
  AudioLines, Captions, Film, Maximize2, Redo2, Scissors, Sparkles, Trash2, Type, Undo2, ZoomIn, ZoomOut,
} from "lucide-react";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { deleteClip, displayBounds, moveClip, splitAt, trimClip } from "../../lib/edits";
import { clamp, fmtTime } from "../../lib/format";
import { captionSpans, layout, type Layout } from "../../lib/layout";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { Edl, Media } from "../../types";
import { IconButton, cx } from "../ui/controls";

const HEADER_W = 92;
const RULER_H = 24;
const TRACK = { video: 58, audio: 42, captions: 30, text: 26 };
const MIN_PPS = 8;
const MAX_PPS = 320;
const HEIGHT_KEY = "frameflow.timelineHeight";

/* ------------------------------------------------------------------ shared helpers */
const peaksCache = new Map<string, Promise<number[]>>();
function usePeaks(url?: string) {
  const [peaks, setPeaks] = useState<number[] | null>(null);
  useEffect(() => {
    if (!url) return setPeaks(null);
    if (!peaksCache.has(url)) peaksCache.set(url, api.peaks(url).catch(() => []));
    let alive = true;
    peaksCache.get(url)!.then((p) => alive && setPeaks(p));
    return () => {
      alive = false;
    };
  }, [url]);
  return peaks;
}

function Waveform({ peaks, step, from, seconds, pps, loop, color }: {
  peaks: number[]; step: number; from: number; seconds: number; pps: number; loop?: number; color: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const width = Math.max(1, Math.min(16000, Math.round(seconds * pps)));
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const h = cv.clientHeight || 24;
    const dpr = window.devicePixelRatio || 1;
    cv.width = width * dpr;
    cv.height = h * dpr;
    const ctx = cv.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, h);
    ctx.fillStyle = color;
    for (let x = 0; x < width; x += 2) {
      let t = from + (x / width) * seconds;
      if (loop) t %= loop;
      const v = peaks[Math.floor(t / step)] ?? 0;
      const bh = Math.max(1, v * (h - 2));
      ctx.fillRect(x, (h - bh) / 2, 1.4, bh);
    }
  }, [peaks, step, from, seconds, width, loop, color]);
  return <canvas ref={ref} style={{ width, height: "100%" }} className="block" />;
}

function Filmstrip({ m, from, seconds, pps, height }: { m: Media; from: number; seconds: number; pps: number; height: number }) {
  const sp = m.info.sprite;
  if (!sp || !m.info.spriteUrl) return null;
  const scale = height / sp.tileH;
  const tw = sp.tileW * scale;
  const width = seconds * pps;
  const n = Math.min(400, Math.ceil(width / tw));
  return (
    <div className="absolute inset-0 flex overflow-hidden opacity-80">
      {Array.from({ length: n }, (_, k) => {
        const t = from + ((k * tw + tw / 2) / pps);
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
        className="pointer-events-auto absolute -left-[6px] top-0 h-3 w-3 cursor-ew-resize rounded-b-sm bg-primary"
        style={{ clipPath: "polygon(0 0,100% 0,100% 55%,50% 100%,0 55%)" }}
      />
      <div className="absolute left-[-0.5px] top-0 h-full w-px bg-primary" />
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

function Ruler({ pps, width, duration }: { pps: number; width: number; duration: number }) {
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
    const key = `drag:trim:${clipId}:${Date.now()}`;
    selectClip(clipId);
    const move = (ev: PointerEvent) => {
      const value = v0 + (ev.clientX - startX) / pps;
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
            title={`${lc.clip.label || m?.name} · ${(lc.clip.srcEnd - lc.clip.srcStart).toFixed(2)}s (source ${lc.clip.srcStart.toFixed(2)}–${lc.clip.srcEnd.toFixed(2)}s)`}
            className={cx(
              "group absolute top-1 cursor-grab overflow-hidden rounded-[4px] bg-clip-video active:cursor-grabbing",
              sel ? "z-10 ring-2 ring-primary" : "ring-1 ring-black/40 hover:ring-[#7FA6FF]/60",
              drag?.from === i && "opacity-40",
            )}
            style={{ left: left + 0.5, width: width - 1, height: TRACK.video - 8 }}
          >
            {m && <Filmstrip m={m} from={lc.clip.srcStart + (b.start - lc.outStart)} seconds={b.end - b.start} pps={pps} height={TRACK.video - 8} />}
            <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-1 bg-gradient-to-b from-black/70 to-transparent px-1.5 pb-2 pt-0.5">
              <span className="truncate text-2xs font-medium text-white">{lc.clip.label || m?.name}</span>
              {width > 70 && <span className="shrink-0 text-2xs tabular-nums text-white/80">{(lc.clip.srcEnd - lc.clip.srcStart).toFixed(1)}s</span>}
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
function AudioTrack({ edl, lay, pps, media }: { edl: Edl; lay: Layout; pps: number; media: Record<string, Media> }) {
  const music = edl.music ? media[edl.music.mediaId] : undefined;
  const musicPeaks = usePeaks(music?.info.peaksUrl);
  const bounds = useMemo(() => displayBounds(lay), [lay]);
  if (music) {
    return (
      <div className="relative" style={{ height: TRACK.audio }}>
        <div className="absolute top-1 overflow-hidden rounded-[4px] bg-clip-audio" style={{ left: 0, width: lay.duration * pps, height: TRACK.audio - 8 }}>
          <div className="absolute inset-0">
            {musicPeaks && music.duration ? (
              <Waveform peaks={musicPeaks} step={music.info.peakStep ?? 0.1} from={0} seconds={lay.duration} pps={pps} loop={music.duration} color="#9FD8B9" />
            ) : null}
          </div>
          <span className="absolute left-1.5 top-0.5 rounded bg-black/40 px-1 text-2xs text-white">
            ♪ {music.name} · {lay.duration.toFixed(1)}s{edl.music?.duck ? " · ducked" : ""}
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="relative" style={{ height: TRACK.audio }}>
      {lay.clips.map((lc, i) => {
        const m = media[lc.clip.mediaId];
        const b = bounds[i];
        return (
          <ClipAudio key={lc.clip.id} m={m} from={lc.clip.srcStart + (b.start - lc.outStart)} seconds={b.end - b.start} left={b.start * pps} pps={pps} />
        );
      })}
    </div>
  );
}

function ClipAudio({ m, from, seconds, left, pps }: { m?: Media; from: number; seconds: number; left: number; pps: number }) {
  const peaks = usePeaks(m?.hasAudio ? m.info.peaksUrl : undefined);
  return (
    <div className="absolute top-1 overflow-hidden rounded-[4px] bg-clip-audio/60" style={{ left: left + 0.5, width: Math.max(2, seconds * pps - 1), height: TRACK.audio - 8 }}>
      {m?.hasAudio ? (
        peaks && <Waveform peaks={peaks} step={m.info.peakStep ?? 0.1} from={from} seconds={seconds} pps={pps} color="#9FD8B9" />
      ) : (
        <span className="absolute left-1.5 top-1 text-2xs text-white/50">No audio</span>
      )}
    </div>
  );
}

function CaptionTrack({ edl, lay, pps }: { edl: Edl; lay: Layout; pps: number }) {
  const spans = useMemo(() => captionSpans(edl.captions, lay.clips), [edl.captions, lay]);
  return (
    <div className="relative" style={{ height: TRACK.captions }}>
      {spans.map((s, i) => (
        <button
          key={`${s.caption.id}-${i}`}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => {
            useStore.getState().seek(s.outStart);
            useStore.getState().setNav("captions");
          }}
          title={s.caption.text}
          className={cx("absolute top-1 overflow-hidden rounded-[4px] px-1.5 text-left text-2xs text-white hover:brightness-125", edl.burnCaptions ? "bg-clip-caption" : "bg-clip-caption/40")}
          style={{ left: s.outStart * pps + 0.5, width: Math.max(2, (s.outEnd - s.outStart) * pps - 1), height: TRACK.captions - 8 }}
        >
          <span className="block truncate leading-[22px]">{s.caption.text}</span>
        </button>
      ))}
    </div>
  );
}

function TextTrack({ edl, pps }: { edl: Edl; pps: number }) {
  return (
    <div className="relative" style={{ height: TRACK.text }}>
      {edl.titles.map((t) => (
        <button
          key={t.id}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={() => {
            useStore.getState().seek(t.start);
            useStore.getState().setNav("text");
          }}
          className="absolute top-1 overflow-hidden rounded-[4px] bg-clip-text px-1.5 text-left text-2xs text-white hover:brightness-125"
          style={{ left: t.start * pps + 0.5, width: Math.max(2, t.duration * pps - 1), height: TRACK.text - 8 }}
        >
          <span className="block truncate leading-[18px]">T · {t.text}</span>
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ main */
export function Timeline() {
  const edl = useStore((s) => s.doc?.edl ?? null);
  const mediaList = useStore((s) => s.media);
  const selectedId = useStore((s) => s.selectedClipId);
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
      return Number(localStorage.getItem(HEIGHT_KEY)) || 250;
    } catch {
      return 250;
    }
  });

  const duration = lay?.duration ?? 0;
  const fitPps = clamp((viewW - 40) / Math.max(5, duration), MIN_PPS, MAX_PPS);
  const zoom = pps ?? fitPps;
  const contentW = Math.max(viewW - HEADER_W, (duration + 4) * zoom);
  const hasCaptions = !!edl && edl.captions.length > 0;
  const hasTitles = !!edl && edl.titles.length > 0;
  const tracksH = RULER_H + TRACK.video + TRACK.audio + TRACK.captions + (hasTitles ? TRACK.text : 0);

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

  const split = () => {
    if (!edl || !lay) return;
    const res = splitAt(edl, lay, useStore.getState().time, selectedId);
    if (!res) return useStore.getState().toast("Move the playhead inside a clip (at least 0.3 s from its edges) to split.");
    updateDoc((d) => ({ ...d, edl: res.edl }));
    selectClip(res.newId);
  };
  const remove = () => {
    if (!edl || !selectedId) return;
    updateDoc((d) => (d.edl ? { ...d, edl: deleteClip(d.edl, selectedId) } : d));
    selectClip(null);
  };

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
  });

  const headers = [
    { icon: Film, label: "Video", h: TRACK.video },
    { icon: AudioLines, label: edl?.music ? "Music" : "Audio", h: TRACK.audio },
    { icon: Captions, label: "Captions", h: TRACK.captions },
    ...(hasTitles ? [{ icon: Type, label: "Text", h: TRACK.text }] : []),
  ];

  return (
    <section className="relative flex shrink-0 flex-col border-t border-line bg-panel" style={{ height }} aria-label="Timeline">
      <div onPointerDown={startResize} className="absolute -top-1 left-0 right-0 z-40 h-2 cursor-ns-resize" title="Drag to resize" />
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line px-2">
        <div className="flex items-center gap-0.5">
          <IconButton label="Undo (⌘Z)" onClick={undo} disabled={!canUndo}><Undo2 size={15} /></IconButton>
          <IconButton label="Redo (⇧⌘Z)" onClick={redo} disabled={!canRedo}><Redo2 size={15} /></IconButton>
          <div className="mx-1.5 h-4 w-px bg-line" />
          <IconButton label="Split at playhead (S)" onClick={split} disabled={!edl?.clips.length}><Scissors size={15} /></IconButton>
          <IconButton label="Delete clip (Del)" onClick={remove} disabled={!selectedId}><Trash2 size={15} /></IconButton>
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

      <div className="flex min-h-0 flex-1">
        <div className="shrink-0 border-r border-line bg-panel" style={{ width: HEADER_W }}>
          <div style={{ height: RULER_H }} />
          {headers.map(({ icon: Icon, label, h }) => (
            <div key={label} className="flex items-center gap-1.5 border-t border-line/50 px-2.5 text-2xs text-fg-muted" style={{ height: h }}>
              <Icon size={13} /> {label}
            </div>
          ))}
        </div>
        <div ref={scrollRef} className="relative min-w-0 flex-1 overflow-x-auto overflow-y-hidden">
          {!edl || !lay || edl.clips.length === 0 ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-fg-muted">
              <Sparkles size={14} className="text-primary" />
              Generate an AI video to build the timeline, or add clips from Media with +.
            </div>
          ) : (
            <div className="relative" style={{ width: contentW, height: tracksH }} onPointerDown={scrub}>
              <div className="cursor-pointer"><Ruler pps={zoom} width={contentW} duration={duration} /></div>
              <div className="border-t border-line/50"><VideoTrack edl={edl} lay={lay} pps={zoom} media={media} /></div>
              <div className="border-t border-line/50"><AudioTrack edl={edl} lay={lay} pps={zoom} media={media} /></div>
              <div className="border-t border-line/50">
                {hasCaptions ? <CaptionTrack edl={edl} lay={lay} pps={zoom} /> : (
                  <div className="flex items-center px-2 text-2xs text-fg-faint" style={{ height: TRACK.captions }}>No captions · turn on Automatic captions or use the Captions panel</div>
                )}
              </div>
              {hasTitles && <div className="border-t border-line/50"><TextTrack edl={edl} pps={zoom} /></div>}
              <Playhead pps={zoom} height={tracksH} onDrag={(e) => { e.stopPropagation(); scrub(e); }} />
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

export const timelineActions: { split?: () => void; remove?: () => void } = {};

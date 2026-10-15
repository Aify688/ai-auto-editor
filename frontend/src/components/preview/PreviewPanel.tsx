import {
  Clapperboard, Loader2, Maximize, Minimize, Pause, Play, RefreshCw, SkipBack, SkipForward, UploadCloud, Volume2,
  VolumeX,
} from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { isActive, startJob } from "../../hooks/useJobs";
import { fmtTime, renderKey } from "../../lib/format";
import { layout } from "../../lib/layout";
import { useStore } from "../../store/project";
import { Empty, IconButton, Segmented, cx } from "../ui/controls";
import { DraftPlayer, RenderedPlayer, SourcePlayer, type Clock } from "./players";

function useFit(ref: React.RefObject<HTMLDivElement>, ratio: number) {
  const [box, setBox] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      const w = Math.min(width, height * ratio);
      setBox({ w: Math.floor(w), h: Math.floor(w / ratio) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref, ratio]);
  return box;
}

function Chip({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "primary" | "warn" }) {
  return (
    <span
      className={cx(
        "rounded px-1.5 py-0.5 text-2xs font-medium tabular-nums",
        tone === "muted" && "bg-panel2 text-fg-muted",
        tone === "primary" && "bg-primary-muted text-primary",
        tone === "warn" && "bg-warn/15 text-warn",
      )}
    >
      {children}
    </span>
  );
}

export function PreviewPanel() {
  const mode = useStore((s) => s.previewMode);
  const setMode = useStore((s) => s.setPreviewMode);
  const edl = useStore((s) => s.doc?.edl ?? null);
  const docAspect = useStore((s) => s.doc?.aspect ?? "16:9");
  const render = useStore((s) => s.project?.render ?? null);
  const mediaList = useStore((s) => s.media);
  const selectedId = useStore((s) => s.selectedMediaId);
  const playing = useStore((s) => s.playing);
  const editTime = useStore((s) => s.time);
  const renderJob = useStore((s) => s.jobs.render);
  const genJob = useStore((s) => s.jobs.generate);

  const [volume, setVolume] = useState(0.9);
  const [muted, setMuted] = useState(false);
  const [full, setFull] = useState(false);
  const [srcClock, setSrcClock] = useState<Clock>({ time: 0, duration: 0 });
  const [srcSeek, setSrcSeek] = useState({ t: 0, n: 0 });
  const stageRef = useRef<HTMLDivElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);

  const media = useMemo(() => Object.fromEntries(mediaList.map((m) => [m.id, m])), [mediaList]);
  const selected = selectedId ? media[selectedId] : undefined;
  const lay = useMemo(() => (edl ? layout(edl) : null), [edl]);
  const hasEdit = !!edl && edl.clips.length > 0;
  const renderCurrent = !!render && hasEdit && renderKey(render.edl) === renderKey(edl);
  const missing = hasEdit && edl!.clips.some((c) => !media[c.mediaId]?.info.proxyUrl);
  const vol = muted ? 0 : volume;

  useEffect(() => {
    setSrcClock({ time: 0, duration: selected?.duration ?? 0 });
  }, [selected?.id, selected?.duration]);

  useEffect(() => {
    const onFs = () => setFull(document.fullscreenElement === shellRef.current);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  const editMode = mode === "edit";
  const ratio = (() => {
    if (editMode) {
      const [a, b] = (edl?.aspect ?? docAspect).split(":").map(Number);
      return a / b;
    }
    if (selected?.width && selected.height) return selected.width / selected.height;
    return 16 / 9;
  })();
  const box = useFit(stageRef, ratio);

  const time = editMode ? editTime : srcClock.time;
  const duration = editMode ? (renderCurrent ? render!.duration : lay?.duration ?? 0) : srcClock.duration;
  const canPlay = editMode ? hasEdit && !missing : !!selected && selected.kind !== "image" && selected.status === "ready";

  const seekTo = (t: number) => {
    const clamped = Math.max(0, Math.min(duration, t));
    if (editMode) useStore.getState().seek(clamped);
    else {
      setSrcSeek((s) => ({ t: clamped, n: s.n + 1 }));
      setSrcClock((c) => ({ ...c, time: clamped }));
    }
  };

  const step = (dir: -1 | 1) => {
    if (editMode && lay) {
      const starts = lay.clips.map((c) => c.outStart);
      const target = dir < 0 ? [...starts].reverse().find((s) => s < time - 0.25) ?? 0 : starts.find((s) => s > time + 0.01);
      if (target != null) seekTo(target);
      return;
    }
    const list = mediaList.filter((m) => m.status === "ready");
    const i = list.findIndex((m) => m.id === selectedId);
    const next = list[i + dir];
    if (next) useStore.getState().selectMedia(next.id);
  };

  const toggleFull = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else shellRef.current?.requestFullscreen().catch(() => undefined);
  };

  const rendering = isActive(renderJob);
  const generating = isActive(genJob);

  let body: React.ReactNode;
  if (editMode) {
    if (!hasEdit)
      body = (
        <Empty
          icon={<Clapperboard size={18} />}
          title={generating ? "Generating your edit…" : "No edit yet"}
          text={generating ? "The result will play here when it's ready." : "Pick a style and click Generate AI Video, or add clips to the timeline."}
        />
      );
    else if (missing) body = <Empty icon={<Loader2 size={18} className="animate-spin" />} title="Preparing preview…" />;
    else if (renderCurrent) body = <RenderedPlayer url={render!.url} volume={vol} />;
    else body = <DraftPlayer edl={edl!} lay={lay!} media={media} volume={vol} />;
  } else {
    body = selected ? (
      selected.status === "ready" ? (
        <SourcePlayer m={selected} volume={vol} seek={srcSeek} onClock={setSrcClock} />
      ) : (
        <Empty icon={<Loader2 size={18} className="animate-spin" />} title="Processing media…" />
      )
    ) : (
      <Empty icon={<UploadCloud size={18} />} title="Nothing to preview" text="Upload a video in the Media panel, then select it to preview here." />
    );
  }

  const label = editMode
    ? hasEdit
      ? renderCurrent
        ? `${render!.width}×${render!.height}`
        : "Draft · 540p proxy"
      : null
    : selected?.width
      ? `${selected.width}×${selected.height}${selected.fps ? ` · ${Math.round(selected.fps)}fps` : ""}`
      : null;

  return (
    <div ref={shellRef} className={cx("flex min-w-0 flex-1 flex-col bg-app", full && "bg-black")}>
      <div className="flex h-10 shrink-0 items-center justify-between gap-2 border-b border-line px-3">
        <div className="w-44">
          <Segmented
            label="Preview source"
            value={mode}
            onChange={setMode}
            options={[{ value: "media", label: "Source" }, { value: "edit", label: "Edit" }]}
          />
        </div>
        <div className="min-w-0 truncate text-xs text-fg-muted">
          {editMode ? (hasEdit ? "Edited video" : "") : selected?.name ?? ""}
        </div>
        <div className="flex items-center gap-1.5">
          <Chip>{editMode ? edl?.aspect ?? docAspect : selected?.width ? `${(ratio).toFixed(2)}:1` : "–"}</Chip>
          {label && <Chip tone={editMode && renderCurrent ? "primary" : "muted"}>{label}</Chip>}
          {editMode && hasEdit && !renderCurrent && (
            <button
              onClick={() => startJob("render")}
              disabled={rendering || generating}
              title="Render the timeline with transitions, color, captions and audio mix"
              className="flex items-center gap-1 rounded bg-warn/15 px-1.5 py-0.5 text-2xs font-medium text-warn transition-colors hover:bg-warn/25 disabled:opacity-70"
            >
              {rendering ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
              {rendering ? `Rendering ${Math.round((renderJob?.progress ?? 0) * 100)}%` : "Render preview"}
            </button>
          )}
        </div>
      </div>

      <div ref={stageRef} className="relative flex min-h-0 flex-1 items-center justify-center p-4">
        <div
          className="overflow-hidden rounded-sm bg-black shadow-[0_0_0_1px_#2A2F38]"
          style={{ width: box.w, height: box.h, containerType: "size" }}
          onClick={() => canPlay && useStore.getState().setPlaying(!playing)}
        >
          {box.w > 0 && body}
        </div>
      </div>

      <div className="shrink-0 border-t border-line px-3 pb-2 pt-1.5">
        <input
          type="range"
          aria-label="Seek"
          className="ff-range ff-seek w-full"
          min={0}
          max={Math.max(0.01, duration)}
          step={0.01}
          value={Math.min(time, duration)}
          disabled={!canPlay}
          onChange={(e) => seekTo(Number(e.target.value))}
          style={{ background: `linear-gradient(to right, #508CFF ${(duration ? time / duration : 0) * 100}%, #383E49 0)` }}
        />
        <div className="mt-1 flex items-center justify-between">
          <div className="flex w-40 items-center gap-1">
            <span className="text-xs tabular-nums text-fg">{fmtTime(time, true)}</span>
            <span className="text-xs tabular-nums text-fg-faint">/ {fmtTime(duration, true)}</span>
          </div>
          <div className="flex items-center gap-1">
            <IconButton label={editMode ? "Previous clip" : "Previous file"} onClick={() => step(-1)} disabled={editMode ? !hasEdit : !selected}>
              <SkipBack size={15} />
            </IconButton>
            <button
              aria-label={playing ? "Pause" : "Play"}
              disabled={!canPlay}
              onClick={() => useStore.getState().setPlaying(!playing)}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-fg text-app transition-transform hover:scale-105 disabled:opacity-35"
            >
              {playing ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" className="ml-0.5" />}
            </button>
            <IconButton label={editMode ? "Next clip" : "Next file"} onClick={() => step(1)} disabled={editMode ? !hasEdit : !selected}>
              <SkipForward size={15} />
            </IconButton>
          </div>
          <div className="flex w-40 items-center justify-end gap-1">
            <IconButton label={muted ? "Unmute" : "Mute"} onClick={() => setMuted(!muted)}>
              {muted || volume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />}
            </IconButton>
            <input
              type="range"
              aria-label="Volume"
              className="ff-range w-16"
              min={0}
              max={1}
              step={0.05}
              value={vol}
              onChange={(e) => {
                setVolume(Number(e.target.value));
                setMuted(false);
              }}
              style={{ background: `linear-gradient(to right, #F5F6F9 ${vol * 100}%, #383E49 0)` }}
            />
            <IconButton label={full ? "Exit fullscreen" : "Fullscreen"} onClick={toggleFull}>
              {full ? <Minimize size={15} /> : <Maximize size={15} />}
            </IconButton>
          </div>
        </div>
      </div>
    </div>
  );
}

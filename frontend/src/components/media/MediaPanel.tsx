import { AlertCircle, Check, Film, Image as ImageIcon, Loader2, Music, Plus, RotateCw, Trash2, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import { ACCEPT, uploadFiles } from "../../hooks/useUpload";
import { fmtBytes, fmtDuration, uid } from "../../lib/format";
import { emptyEdl } from "../../lib/styles";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { Media } from "../../types";
import { Button, Empty, PanelHeader, cx } from "../ui/controls";

const KIND_ICON = { video: Film, image: ImageIcon, audio: Music };

export function addToTimeline(m: Media) {
  const s = useStore.getState();
  if (m.status !== "ready" || !m.duration || m.kind === "audio") return;
  s.updateDoc((d) => {
    const edl = d.edl ?? emptyEdl(d);
    const len = m.kind === "image" ? 3 : m.duration!;
    return {
      ...d,
      edl: {
        ...edl,
        clips: [
          ...edl.clips,
          { id: uid("c"), mediaId: m.id, srcStart: 0, srcEnd: Math.round(len * 1000) / 1000, sceneBreak: true,
            label: m.name.replace(/\.[^.]+$/, ""), focusX: 0.5, focusY: 0.5, score: null },
        ],
      },
    };
  });
  s.setPreviewMode("edit");
  s.toast(`Added ${m.name} to the timeline`);
}

function MediaCard({ m, index, onDragStart, onDrop }: {
  m: Media; index: number; onDragStart: (i: number) => void; onDrop: (i: number) => void;
}) {
  const selected = useStore((s) => s.selectedMediaId === m.id);
  const usedInEdl = useStore((s) => !!s.doc?.edl?.clips.some((c) => c.mediaId === m.id) || s.doc?.edl?.music?.mediaId === m.id);
  const isMusic = useStore((s) => s.doc?.settings.musicId === m.id);
  const [confirm, setConfirm] = useState(false);
  const [over, setOver] = useState(false);
  const Icon = KIND_ICON[m.kind];

  const remove = async () => {
    const s = useStore.getState();
    try {
      await api.deleteMedia(m.id);
      s.setMedia(s.media.filter((x) => x.id !== m.id));
      if (s.selectedMediaId === m.id) s.selectMedia(null);
      if (usedInEdl || isMusic) {
        s.updateDoc((d) => ({
          ...d,
          settings: d.settings.musicId === m.id ? { ...d.settings, musicId: null } : d.settings,
          edl: d.edl && {
            ...d.edl,
            clips: d.edl.clips.filter((c) => c.mediaId !== m.id),
            captions: d.edl.captions.filter((c) => c.mediaId !== m.id),
            music: d.edl.music?.mediaId === m.id ? null : d.edl.music,
          },
        }));
      }
    } catch (e) {
      s.toast((e as Error).message, "error");
    }
  };

  const retry = async () => {
    try {
      await api.retryMedia(m.id);
      await useStore.getState().refreshMedia();
    } catch (e) {
      useStore.getState().toast((e as Error).message, "error");
    }
  };

  return (
    <div
      draggable={!confirm}
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/x-frameflow-media", m.id);
        onDragStart(index);
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("text/x-frameflow-media")) {
          e.preventDefault();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        if (e.dataTransfer.types.includes("text/x-frameflow-media")) {
          e.preventDefault();
          e.stopPropagation();
          onDrop(index);
        }
      }}
      onClick={() => m.status === "ready" && useStore.getState().selectMedia(m.id)}
      className={cx(
        "group relative cursor-pointer overflow-hidden rounded-xl border-2 bg-panel2 transition-colors",
        selected ? "border-primary" : "border-transparent hover:border-line",
        over && "ring-2 ring-primary/60",
      )}
    >
      <div className="relative aspect-video bg-[#15171c]">
        {m.info.thumbUrl ? (
          <img src={m.info.thumbUrl} alt="" draggable={false} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center text-fg-faint">
            <Icon size={22} strokeWidth={1.5} />
          </div>
        )}
        {m.status === "processing" && (
          <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/55 text-2xs text-fg">
            <Loader2 size={13} className="animate-spin" /> Processing
          </div>
        )}
        {m.status === "error" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-black/70 px-2 text-center text-2xs text-danger" title={m.error ?? ""}>
            <AlertCircle size={14} />
            <span className="line-clamp-2">{m.error}</span>
            <button onClick={(e) => { e.stopPropagation(); retry(); }} className="mt-0.5 flex items-center gap-1 text-fg-muted hover:text-fg">
              <RotateCw size={11} /> Retry
            </button>
          </div>
        )}
        {m.duration != null && m.kind !== "image" && (
          <span className="absolute bottom-1.5 right-1.5 rounded-full bg-black/70 px-1.5 text-2xs tabular-nums text-fg">
            {fmtDuration(m.duration)}
          </span>
        )}
        {usedInEdl && m.kind !== "audio" && (
          <span className="absolute bottom-1.5 left-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-ink" title="Used in your edit">
            <Check size={12} strokeWidth={3} />
          </span>
        )}
        {isMusic && (
          <span className="absolute left-1 top-1 rounded bg-clip-audio px-1 text-2xs text-fg">Music</span>
        )}
        <div className="absolute right-1 top-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          {m.kind !== "audio" && m.status === "ready" && (
            <button
              title="Add to timeline"
              aria-label="Add to timeline"
              onClick={(e) => { e.stopPropagation(); addToTimeline(m); }}
              className="flex h-7 w-7 items-center justify-center rounded-lg bg-black/70 text-fg hover:bg-primary hover:text-primary-ink"
            >
              <Plus size={13} />
            </button>
          )}
          <button
            title="Remove"
            aria-label="Remove file"
            onClick={(e) => { e.stopPropagation(); setConfirm(true); }}
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-black/70 text-fg hover:bg-danger"
          >
            <Trash2 size={12} />
          </button>
        </div>
        {confirm && (
          <div onClick={(e) => e.stopPropagation()} className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 bg-black/85 p-2 text-center">
            <span className="text-2xs text-fg">{usedInEdl || isMusic ? "Used in your edit. Remove anyway?" : "Remove this file?"}</span>
            <div className="flex gap-1">
              <Button size="sm" variant="danger" onClick={remove}>Remove</Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>Cancel</Button>
            </div>
          </div>
        )}
      </div>
      <div className="px-2 py-1.5">
        <div className="truncate text-xs text-fg" title={m.name}>{m.name}</div>
        <div className="flex items-center gap-1 text-2xs text-fg-faint">
          <Icon size={10} />
          <span className="uppercase">{m.ext}</span>
          {m.width ? <span>· {m.width}×{m.height}</span> : null}
          {m.kind === "audio" && <span>· {fmtBytes(m.size)}</span>}
        </div>
      </div>
    </div>
  );
}

export function MediaPanel() {
  const media = useStore((s) => s.media);
  const uploads = useStore((s) => s.uploads);
  const setUploads = useStore((s) => s.setUploads);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragFrom = useRef<number | null>(null);
  const [dropping, setDropping] = useState(false);

  const reorder = async (to: number) => {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from == null || from === to) return;
    const s = useStore.getState();
    const next = [...s.media];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    s.setMedia(next.map((m, i) => ({ ...m, position: i })));
    try {
      s.setMedia(await api.reorderMedia(s.project!.id, next.map((m) => m.id)));
    } catch (e) {
      s.toast((e as Error).message, "error");
      s.refreshMedia();
    }
  };

  const onFiles = (list: FileList | null) => list && list.length && uploadFiles(Array.from(list));

  return (
    <div
      className="flex h-full flex-col"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDropping(true);
        }
      }}
      onDragLeave={(e) => e.currentTarget === e.target && setDropping(false)}
      onDrop={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDropping(false);
          onFiles(e.dataTransfer.files);
        }
      }}
    >
      <PanelHeader
        title="Media"
        action={
          <Button variant="primary" size="sm" icon={<UploadCloud size={13} />} onClick={() => inputRef.current?.click()}>
            Upload Files
          </Button>
        }
      />
      <input ref={inputRef} type="file" multiple accept={ACCEPT} hidden onChange={(e) => { onFiles(e.target.files); e.target.value = ""; }} />

      <div className="px-4">
        <button
          onClick={() => inputRef.current?.click()}
          className={cx(
            "flex w-full flex-col items-center justify-center gap-1 rounded-xl border-[1.5px] border-dashed py-4 text-center transition-colors",
            dropping ? "border-primary bg-primary-muted" : "border-line hover:border-[#4A5160] hover:bg-panel2/50",
          )}
        >
          <UploadCloud size={18} className={dropping ? "text-primary" : "text-fg-muted"} />
          <span className="text-xs text-fg">Drop files here or click to browse</span>
          <span className="text-2xs text-fg-faint">MP4 · MOV · WebM · JPG · PNG · MP3 · WAV</span>
        </button>
      </div>

      {uploads.length > 0 && (
        <div className="mt-3 space-y-1.5 px-4">
          {uploads.map((u) => (
            <div key={u.id} className="rounded border border-line bg-panel2 px-2 py-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-xs text-fg">{u.name}</span>
                {u.error ? (
                  <button aria-label="Dismiss" onClick={() => setUploads((x) => x.filter((y) => y.id !== u.id))} className="text-fg-muted hover:text-fg">
                    <X size={12} />
                  </button>
                ) : (
                  <span className="text-2xs tabular-nums text-fg-muted">{Math.round(u.progress * 100)}%</span>
                )}
              </div>
              {u.error ? (
                <div className="mt-0.5 text-2xs text-danger">{u.error}</div>
              ) : (
                <div className="mt-1 h-1 overflow-hidden rounded bg-line">
                  <div className="h-full bg-primary transition-[width] duration-150" style={{ width: `${u.progress * 100}%` }} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 flex-1 overflow-y-auto px-4 pb-4">
        {media.length === 0 && uploads.length === 0 ? (
          <Empty icon={<Film size={18} />} title="No media yet" text="Upload videos, photos or music to start your edit." />
        ) : (
          <>
            <div className="mb-2 flex items-center justify-between text-2xs text-fg-faint">
              <span>{media.length} file{media.length === 1 ? "" : "s"}</span>
              <span>Drag to reorder</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {media.map((m, i) => (
                <MediaCard key={m.id} m={m} index={i} onDragStart={(idx) => (dragFrom.current = idx)} onDrop={reorder} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

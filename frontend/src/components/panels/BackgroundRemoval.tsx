import { Eraser, ImageOff, Loader2, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cancelJob, isActive, startJob } from "../../hooks/useJobs";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { BgMode, BgRemoval, EdlClip } from "../../types";
import { Button, Field, Segmented, Select, Slider, Toggle } from "../ui/controls";

const DEFAULT: BgRemoval = { enabled: false, mode: "color", color: "#00B140", blur: 50, bgMediaId: null };
const MODES: { value: BgMode; label: string }[] = [
  { value: "color", label: "Color" },
  { value: "image", label: "Image" },
  { value: "video", label: "Video" },
  { value: "blur", label: "Blur" },
];

/** AI Background Removal for the selected clip. The source file is never changed: the renderer composites the effect. */
export function BackgroundRemoval({ clip, outStart, patch }: { clip: EdlClip; outStart: number; patch: (p: Partial<EdlClip>, key: string) => void }) {
  const media = useStore((s) => s.media);
  const time = useStore((s) => s.time);
  const sys = useStore((s) => s.system?.backgroundRemoval);
  const job = useStore((s) => s.jobs.matte);
  const renderJob = useStore((s) => s.jobs.render);
  const cfg = clip.bgRemoval ?? DEFAULT;
  const source = media.find((m) => m.id === clip.mediaId);
  const [ready, setReady] = useState<boolean | null>(null);
  const [preview, setPreview] = useState<{ url: string; t: number } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastUrl = useRef<string | null>(null);
  const running = isActive(job) && job?.params && (job.params as { mediaId?: string }).mediaId === clip.mediaId;
  const rendering = isActive(renderJob);

  useEffect(() => {
    let alive = true;
    setReady(null);
    api.matteStatus(clip.mediaId).then((r) => alive && setReady(r.ready)).catch(() => alive && setReady(false));
    return () => { alive = false; };
  }, [clip.mediaId, job?.status]);

  useEffect(() => () => { if (lastUrl.current) URL.revokeObjectURL(lastUrl.current); }, []);

  const set = (p: Partial<BgRemoval>) => patch({ bgRemoval: { ...cfg, ...p } }, `bg-${clip.id}`);
  const unavailable = sys && !sys.ok;
  const candidates = media.filter((m) => m.status === "ready" && m.id !== clip.mediaId && m.kind === (cfg.mode === "image" ? "image" : "video"));
  const needsBg = (cfg.mode === "image" || cfg.mode === "video") && !cfg.bgMediaId;

  const analyse = async () => {
    setError(null);
    try {
      useStore.getState().setJob(await api.startMatte(clip.mediaId));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const toggle = (on: boolean) => {
    set({ enabled: on });
    if (on && ready === false && !running && !unavailable) analyse();
  };

  const makePreview = async () => {
    setError(null);
    setPreviewing(true);
    const t = Math.max(clip.srcStart, Math.min(clip.srcEnd - 0.05, clip.srcStart + (time - outStart)));
    try {
      const url = await api.bgPreview(clip.mediaId, { t, mode: cfg.mode, color: cfg.color, blur: cfg.blur, bgMediaId: cfg.bgMediaId });
      if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
      lastUrl.current = url;
      setPreview({ url, t });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <section className="rounded-xl border border-line bg-panel2 px-3 py-3">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">
          <Eraser size={12} /> AI Background Removal
        </h3>
        <Toggle label="Enable AI Background Removal" checked={cfg.enabled} disabled={!!unavailable} onChange={toggle} />
      </div>
      {unavailable ? (
        <p className="mt-2 text-2xs text-danger">Unavailable: {sys?.hint}</p>
      ) : (
        <p className="mt-1 text-2xs text-fg-faint">
          Keeps the person, replaces the rest. The original video is not changed.{sys && !sys.modelCached ? ` First use downloads a ${sys.downloadMb ?? 26} MB model.` : ""}
        </p>
      )}

      <div className="mt-2 space-y-1">
        <Field label="Background">
          <Segmented<BgMode> label="Background type" value={cfg.mode} options={MODES} onChange={(mode) => set({ mode, bgMediaId: null })} />
        </Field>
        {cfg.mode === "color" && (
          <Field label="Colour">
            <div className="flex items-center gap-2">
              <input type="color" aria-label="Background colour" value={cfg.color} onChange={(e) => set({ color: e.target.value })}
                className="h-7 w-10 cursor-pointer rounded border border-line bg-transparent" />
              <span className="text-2xs tabular-nums text-fg-muted">{cfg.color}</span>
            </div>
          </Field>
        )}
        {cfg.mode === "blur" && (
          <div className="py-1">
            <div className="mb-1 flex justify-between text-xs"><span>Blur</span><span className="tabular-nums text-fg-muted">{Math.round(cfg.blur)}%</span></div>
            <Slider label="Background blur" min={5} max={100} step={1} value={cfg.blur} onChange={(v) => set({ blur: v })} />
          </div>
        )}
        {(cfg.mode === "image" || cfg.mode === "video") && (
          candidates.length ? (
            <Field label={cfg.mode === "image" ? "Image" : "Video"} hint="From your media">
              <Select
                label="Background media"
                className="w-40"
                value={cfg.bgMediaId ?? ""}
                options={[{ value: "", label: "Choose…" }, ...candidates.map((m) => ({ value: m.id, label: m.name }))]}
                onChange={(v) => set({ bgMediaId: v || null })}
              />
            </Field>
          ) : (
            <p className="flex items-center gap-1.5 py-1 text-2xs text-fg-faint">
              <ImageOff size={12} /> Upload {cfg.mode === "image" ? "an image" : "another video"} in Media to use it as the background.
            </p>
          )
        )}
      </div>

      <div className="mt-2 flex gap-2">
        <Button size="sm" className="flex-1" disabled={!!unavailable || previewing || needsBg} onClick={makePreview}
          icon={previewing ? <Loader2 size={12} className="animate-spin" /> : undefined}>
          {previewing ? "Finding subject…" : "Preview frame"}
        </Button>
        <Button size="sm" className="flex-1" disabled={!cfg.enabled || rendering || !!unavailable || needsBg} onClick={() => startJob("render")}
          icon={rendering ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}>
          Render preview
        </Button>
      </div>

      {preview && (
        <figure className="mt-2">
          <img src={preview.url} alt="Background removal preview" className="w-full rounded-lg border border-line" />
          <figcaption className="mt-1 text-2xs text-fg-faint">Preview at {preview.t.toFixed(1)}s. Turn the effect on to apply it to this clip.</figcaption>
        </figure>
      )}

      {running && job ? (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between text-2xs text-fg">
            <span className="flex items-center gap-1.5"><Loader2 size={11} className="animate-spin text-primary" /> {job.message}</span>
            <span className="tabular-nums text-fg-muted">{Math.round(job.progress * 100)}%</span>
          </div>
          <div className="h-1 overflow-hidden rounded bg-line"><div className="h-full bg-primary transition-[width]" style={{ width: `${job.progress * 100}%` }} /></div>
          <Button size="sm" variant="ghost" className="mt-1 w-full" icon={<X size={12} />} onClick={() => cancelJob(job)}>Cancel</Button>
        </div>
      ) : (
        <div className="mt-2 flex items-center justify-between text-2xs">
          <span className={ready ? "text-success" : "text-fg-faint"}>
            {ready === null ? "Checking…" : ready ? `Subject found in ${source?.name ?? "this video"}` : "Subject not analysed yet"}
          </span>
          {!ready && ready !== null && !unavailable && <button onClick={analyse} className="text-primary hover:underline">Analyse now</button>}
        </div>
      )}
      {(error || (job?.status === "failed" && !running)) && <p className="mt-1 text-2xs text-danger">{error ?? job?.error}</p>}
    </section>
  );
}

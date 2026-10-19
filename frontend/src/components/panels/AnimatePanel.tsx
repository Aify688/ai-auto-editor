import { AlertTriangle, Download, ImagePlus, Loader2, Plus, RotateCw, Sparkles, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cancelJob, isActive, retryJob } from "../../hooks/useJobs";
import { uploadFiles } from "../../hooks/useUpload";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { AnimateOptions, ImageToVideoStatus } from "../../types/animate";
import { addToTimeline } from "../media/MediaPanel";
import { Button, Empty, Field, PanelHeader, Segmented, cx } from "../ui/controls";

const DURATIONS = [3, 5, 8] as const;
const ASPECTS: AnimateOptions["aspect"][] = ["16:9", "9:16", "1:1"];
const INTENSITIES: { value: AnimateOptions["intensity"]; label: string }[] = [
  { value: "low", label: "Subtle" },
  { value: "medium", label: "Natural" },
  { value: "high", label: "Lively" },
];

/** Image to Animation: pick an image, optionally describe the motion, and a real image-to-video service animates it. */
export function AnimatePanel() {
  const project = useStore((s) => s.project);
  const media = useStore((s) => s.media);
  const job = useStore((s) => s.jobs.animate);
  const setJob = useStore((s) => s.setJob);
  const toast = useStore((s) => s.toast);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState<ImageToVideoStatus | null>(null);
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [seconds, setSeconds] = useState<number>(5);
  const [aspect, setAspect] = useState<AnimateOptions["aspect"]>("16:9");
  const [intensity, setIntensity] = useState<AnimateOptions["intensity"]>("medium");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api.imageToVideo().then(setStatus).catch(() => setStatus({ configured: false, provider: "", model: "", aspects: [], minSeconds: 2, maxSeconds: 10, hint: "Couldn't reach the server." }));
  }, []);

  const images = media.filter((m) => m.kind === "image");
  const picked = images.find((m) => m.id === pickedId) ?? images[0] ?? null;
  const running = isActive(job) || starting;
  const forThis = job && picked && job.params.mediaId === picked.id ? job : null;
  const result = forThis?.status === "done" ? media.find((m) => m.id === forThis.result?.mediaId) : undefined;
  const ready = !!status?.configured && picked?.status === "ready" && !running;

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    const before = new Set(useStore.getState().media.map((m) => m.id));
    await uploadFiles(Array.from(files).filter((f) => /\.(jpe?g|png)$/i.test(f.name)));
    const added = useStore.getState().media.find((m) => m.kind === "image" && !before.has(m.id));
    if (added) setPickedId(added.id);
  };

  const start = async () => {
    if (!project || !picked || running) return;
    setStarting(true);
    try {
      setJob(await api.animate(project.id, { mediaId: picked.id, prompt: prompt.trim(), seconds, aspect, intensity }));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Animate" subtitle="Turn one image into a moving clip." action={<Button size="sm" icon={<ImagePlus size={13} />} onClick={() => input.current?.click()}>Upload image</Button>} />
      <input ref={input} type="file" accept=".jpg,.jpeg,.png" hidden onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
      <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        {status && !status.configured && (
          <div className="flex gap-2 rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-2xs text-warn" role="status">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <span className="break-words">{status.hint}</span>
          </div>
        )}

        {!images.length ? (
          <Empty icon={<ImagePlus size={18} />} title="No images yet" text="Upload a JPG or PNG, or add one in Media." action={<Button size="sm" onClick={() => input.current?.click()}>Upload image</Button>} />
        ) : (
          <>
            <div className="grid grid-cols-4 gap-1.5" role="radiogroup" aria-label="Image to animate">
              {images.map((m) => (
                <button key={m.id} role="radio" aria-checked={picked?.id === m.id} onClick={() => setPickedId(m.id)} disabled={running}
                  className={cx("aspect-square overflow-hidden rounded-lg border", picked?.id === m.id ? "border-primary" : "border-line hover:border-[#4A5160]")}>
                  {m.info.thumbUrl && <img src={m.info.thumbUrl} alt={m.name} className="h-full w-full object-cover" />}
                </button>
              ))}
            </div>

            {picked && (
              <div className="overflow-hidden rounded-xl border border-line bg-black">
                {result?.info.url ? (
                  <video key={result.id} src={result.info.url} controls loop playsInline className="max-h-72 w-full object-contain" aria-label="Animation preview" />
                ) : (
                  <img src={picked.info.url ?? picked.info.thumbUrl} alt={picked.name} className="max-h-72 w-full object-contain" />
                )}
              </div>
            )}

            <div className="text-xs">Motion <span className="text-fg-faint">(optional)</span></div>
            <textarea aria-label="Motion prompt" value={prompt} maxLength={1000} onChange={(e) => setPrompt(e.target.value)} disabled={running}
              placeholder="Describe the movement, e.g. hair blowing in the wind, slow zoom in. Leave blank and it will be chosen from the image."
              className="-mt-3 h-20 w-full resize-none rounded-lg border border-line bg-app p-2 text-xs text-fg outline-none focus:border-primary" />

            <Field label="Duration"><Segmented label="Duration" value={seconds} options={DURATIONS.map((d) => ({ value: d, label: `${d}s` }))} onChange={setSeconds} /></Field>
            <Field label="Aspect ratio"><Segmented label="Aspect ratio" value={aspect} options={ASPECTS.map((a) => ({ value: a, label: a }))} onChange={setAspect} /></Field>
            <Field label="Motion intensity"><Segmented label="Motion intensity" value={intensity} options={INTENSITIES} onChange={setIntensity} /></Field>

            {running ? (
              <div className="rounded-xl border border-line bg-panel2 p-3" role="status" aria-live="polite">
                <div className="flex items-center justify-between text-xs"><span className="flex items-center gap-2"><Loader2 size={14} className="animate-spin" />{job?.message ?? "Starting…"}</span><span className="tabular-nums text-fg-muted">{Math.round((job?.progress ?? 0) * 100)}%</span></div>
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-line"><div className="h-full rounded bg-primary transition-all" style={{ width: `${Math.max(3, (job?.progress ?? 0) * 100)}%` }} /></div>
                <p className="mt-2 text-2xs text-fg-faint">AI video usually takes one to three minutes.</p>
                {job && isActive(job) && <Button size="sm" className="mt-2 w-full" icon={<X size={12} />} onClick={() => cancelJob(job)}>Cancel</Button>}
              </div>
            ) : (
              <>
                {forThis?.status === "failed" && (
                  <div className="rounded-xl border border-danger/40 bg-danger/10 p-3 text-xs" role="alert">
                    <div className="flex gap-2 text-danger"><AlertTriangle size={14} className="mt-px shrink-0" /><span className="break-words">{forThis.error ?? "The animation failed."}</span></div>
                    <Button size="sm" className="mt-2" icon={<RotateCw size={12} />} onClick={() => retryJob(forThis)}>Retry</Button>
                  </div>
                )}
                <Button variant="primary" className="w-full" icon={<Sparkles size={16} />} disabled={!ready} onClick={start}
                  title={!status?.configured ? "Set up an image-to-video service first" : undefined}>
                  {result ? "Regenerate" : "Animate"}
                </Button>
                {result && (
                  <div className="flex gap-2">
                    <Button className="flex-1" icon={<Plus size={14} />} onClick={() => addToTimeline(result)}>Add to timeline</Button>
                    <a href={result.info.url} download={result.name} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg border border-line bg-panel2 text-xs font-medium text-fg hover:border-[#4A5160]"><Download size={14} /> Download</a>
                  </div>
                )}
                <p className="text-center text-2xs text-fg-faint">Your original image is never changed. The animation is saved to Media.</p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

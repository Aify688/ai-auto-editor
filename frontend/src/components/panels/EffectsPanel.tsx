import { Wand2 } from "lucide-react";
import { LOOKS, STYLES, TRANSITIONS } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { Look } from "../../types";
import { Empty, Field, PanelHeader, Segmented, Select, Slider, cx } from "../ui/controls";

export function EffectsPanel() {
  const doc = useStore((s) => s.doc!);
  const thumb = useStore((s) => {
    const first = s.doc?.edl?.clips[0]?.mediaId;
    return (first ? s.media.find((m) => m.id === first) : s.media.find((m) => m.kind !== "audio" && m.info.thumbUrl))?.info.thumbUrl;
  });
  const updateDoc = useStore((s) => s.updateDoc);
  const edl = doc.edl;
  const look: Look = edl?.look ?? doc.settings.look ?? STYLES[doc.style].look;

  const setLook = (v: Look) =>
    updateDoc((d) => ({ ...d, settings: { ...d.settings, look: v }, edl: d.edl && { ...d.edl, look: v } }));

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Effects" subtitle="Color grade, transitions and framing." />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-fg-muted">Color grade</h3>
        <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Color grade">
          {LOOKS.map((l) => (
            <button
              key={l.value}
              role="radio"
              aria-checked={look === l.value}
              onClick={() => setLook(l.value)}
              className={cx("overflow-hidden rounded border text-left transition-colors", look === l.value ? "border-primary" : "border-line hover:border-[#4A5160]")}
            >
              <div className="aspect-video bg-panel2">
                {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" style={{ filter: l.css }} /> : <div className="h-full w-full bg-gradient-to-br from-[#4a5a78] to-[#2b2f38]" style={{ filter: l.css }} />}
              </div>
              <div className="px-1.5 py-1 text-2xs text-fg">{l.label}</div>
            </button>
          ))}
        </div>
        <p className="mt-1 text-2xs text-fg-faint">Swatches approximate the FFmpeg grade applied on render.</p>

        <h3 className="mb-1 mt-5 text-xs font-medium uppercase tracking-wide text-fg-muted">Transitions</h3>
        {!edl ? (
          <p className="text-2xs text-fg-faint">Set by the editing style; adjustable after generating.</p>
        ) : (
          <>
            <Field label="Type">
              <Select
                label="Transition type"
                className="w-36"
                value={edl.transition?.type ?? "none"}
                options={[{ value: "none", label: "None (cuts)" }, ...TRANSITIONS]}
                onChange={(v) =>
                  updateDoc((d) => ({
                    ...d,
                    settings: { ...d.settings, transitions: v !== "none" },
                    edl: d.edl && { ...d.edl, transition: v === "none" ? null : { type: v, duration: d.edl.transition?.duration ?? STYLES[d.edl.style].transition.duration } },
                  }))
                }
              />
            </Field>
            {edl.transition && (
              <Field label="Duration" hint={`${edl.transition.duration.toFixed(2)}s (shortened to fit short clips)`}>
                <div className="w-32">
                  <Slider label="Transition duration" min={0.1} max={2} step={0.05} value={edl.transition.duration}
                    onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl?.transition ? { ...d.edl, transition: { ...d.edl.transition, duration: v } } : d.edl }), { coalesce: "trdur" })} />
                </div>
              </Field>
            )}
          </>
        )}

        <h3 className="mb-1.5 mt-5 text-xs font-medium uppercase tracking-wide text-fg-muted">Framing</h3>
        <Segmented
          label="Framing"
          value={(edl?.fit ?? (doc.settings.smartCrop ? "crop" : "blur")) as "crop" | "blur"}
          options={[{ value: "crop", label: "Smart crop" }, { value: "blur", label: "Blur fit" }]}
          onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, smartCrop: v === "crop" }, edl: d.edl && { ...d.edl, fit: v } }))}
        />
        <p className="mt-1 text-2xs text-fg-faint">
          {(edl?.fit ?? (doc.settings.smartCrop ? "crop" : "blur")) === "crop" ? "Fills the frame, keeping faces and motion in view." : "Shows the whole shot over a blurred copy."}
        </p>
        {!edl && !thumb && <Empty icon={<Wand2 size={18} />} title="Upload media to preview grades" />}
      </div>
    </div>
  );
}

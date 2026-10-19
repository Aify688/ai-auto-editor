import { Ban, Wand2, X } from "lucide-react";
import { useState } from "react";
import { EFFECTS, FILTERS, MAX_EFFECTS, clipFilterCss } from "../../lib/effects";
import { LOOKS, STYLES, TRANSITIONS } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { ClipEffect, EdlClip, Look } from "../../types";
import { Empty, Field, PanelHeader, Segmented, Select, Slider, cx } from "../ui/controls";

function ProjectTab() {
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
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Color grade</h3>
        <div className="grid grid-cols-3 gap-1.5" role="radiogroup" aria-label="Color grade">
          {LOOKS.map((l) => (
            <button
              key={l.value}
              role="radio"
              aria-checked={look === l.value}
              onClick={() => setLook(l.value)}
              className={cx("overflow-hidden rounded-lg border text-left transition-colors", look === l.value ? "border-primary" : "border-line hover:border-[#4A5160]")}
            >
              <div className="aspect-video bg-panel2">
                {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" style={{ filter: l.css }} /> : <div className="h-full w-full bg-gradient-to-br from-[#4a5a78] to-[#2b2f38]" style={{ filter: l.css }} />}
              </div>
              <div className="px-1.5 py-1 text-2xs text-fg">{l.label}</div>
            </button>
          ))}
        </div>
        <p className="mt-1 text-2xs text-fg-faint">Swatches approximate the FFmpeg grade applied on render.</p>

        <h3 className="mb-1 mt-5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Transitions</h3>
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

        <h3 className="mb-1.5 mt-5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Framing</h3>
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

type Tab = "filters" | "effects" | "transitions" | "project";
const TABS: { key: Tab; label: string }[] = [
  { key: "filters", label: "Filters" },
  { key: "effects", label: "Effects" },
  { key: "transitions", label: "Transitions" },
  { key: "project", label: "Grade" },
];

/** CapCut-style library. Filters, effects and transitions apply to the selected clip, or to every clip when none is. */
export function EffectsPanel() {
  const [tab, setTab] = useState<Tab>("filters");
  const doc = useStore((s) => s.doc!);
  const selected = useStore((s) => s.selectedClipId);
  const edl = doc.edl;
  const clip = edl?.clips.find((c) => c.id === selected) ?? null;
  const thumb = useStore((s) => {
    const first = (clip ?? s.doc?.edl?.clips[0])?.mediaId;
    return (first ? s.media.find((m) => m.id === first) : s.media.find((m) => m.kind !== "audio" && m.info.thumbUrl))?.info.thumbUrl;
  });
  const updateDoc = useStore((s) => s.updateDoc);

  /** Edit the selected clip, or all clips when nothing is selected. */
  const patchClips = (fn: (c: EdlClip) => EdlClip, coalesce?: string) =>
    updateDoc((d) => (d.edl ? { ...d, edl: { ...d.edl, clips: d.edl.clips.map((c) => (!selected || c.id === selected ? fn(c) : c)) } } : d), { coalesce });

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Effects" subtitle={clip ? `Applies to ${clip.label || "the selected clip"}.` : edl?.clips.length ? "Applies to all clips. Select a clip to target one." : "Generate or add clips first."} />
      <div className="px-4 pb-2">
        <Segmented label="Library" value={tab} options={TABS.map((t) => ({ value: t.key, label: t.label }))} onChange={setTab} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {tab === "project" ? <ProjectTab /> : !edl?.clips.length ? (
          <Empty icon={<Wand2 size={18} />} title="No clips yet" text="Effects, filters and transitions are applied to clips on the timeline." />
        ) : tab === "filters" ? (
          <FiltersTab thumb={thumb} clip={clip} patchClips={patchClips} />
        ) : tab === "effects" ? (
          <EffectsTab thumb={thumb} clip={clip} patchClips={patchClips} />
        ) : (
          <TransitionsTab thumb={thumb} clip={clip} patchClips={patchClips} />
        )}
      </div>
    </div>
  );
}

interface TabProps {
  thumb?: string;
  clip: EdlClip | null;
  patchClips: (fn: (c: EdlClip) => EdlClip, coalesce?: string) => void;
}

function Tile({ label, css, thumb, active, onClick }: { label: string; css?: string; thumb?: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cx("overflow-hidden rounded-lg border text-left transition-colors", active ? "border-primary" : "border-line hover:border-[#4A5160]")}
    >
      <div className="aspect-video bg-panel2">
        {thumb ? <img src={thumb} alt="" className="h-full w-full object-cover" style={{ filter: css || "none" }} /> : <div className="h-full w-full bg-gradient-to-br from-[#4a5a78] to-[#2b2f38]" style={{ filter: css || "none" }} />}
      </div>
      <div className="truncate px-1.5 py-1 text-2xs text-fg">{label}</div>
    </button>
  );
}

function FiltersTab({ thumb, clip, patchClips }: TabProps) {
  const current = clip?.filter ?? null;
  return (
    <div className="px-4 pb-4">
      <div className="grid grid-cols-3 gap-1.5">
        <Tile label="None" thumb={thumb} active={!current} onClick={() => patchClips((c) => ({ ...c, filter: null }))} />
        {FILTERS.map((f) => (
          <Tile key={f.id} label={f.label} css={f.css} thumb={thumb} active={current?.id === f.id} onClick={() => patchClips((c) => ({ ...c, filter: { id: f.id, strength: c.filter?.id === f.id ? c.filter.strength : 1 } }))} />
        ))}
      </div>
      {current && (
        <div className="mt-3">
          <Field label="Strength" hint={`${Math.round(current.strength * 100)}%`}>
            <div className="w-36">
              <Slider label="Filter strength" min={0} max={1} step={0.01} value={current.strength} onChange={(v) => patchClips((c) => (c.filter ? { ...c, filter: { ...c.filter, strength: v } } : c), "flt-strength")} />
            </div>
          </Field>
        </div>
      )}
      <p className="mt-2 text-2xs text-fg-faint">Swatches approximate the FFmpeg result. Filters stack on top of the project Grade.</p>
    </div>
  );
}

function EffectsTab({ thumb, clip, patchClips }: TabProps) {
  const list: ClipEffect[] = clip?.effects ?? [];
  const toggle = (id: string) =>
    patchClips((c) => {
      const has = c.effects?.some((e) => e.id === id);
      if (has) return { ...c, effects: (c.effects ?? []).filter((e) => e.id !== id) };
      if ((c.effects?.length ?? 0) >= MAX_EFFECTS) return c;
      return { ...c, effects: [...(c.effects ?? []), { id, amount: 0.5 }] };
    });
  return (
    <div className="px-4 pb-4">
      <div className="grid grid-cols-3 gap-1.5">
        {EFFECTS.map((e) => (
          <Tile key={e.id} label={e.label} css={e.css ? clipFilterCss(null, [{ id: e.id, amount: 0.6 }]) : ""} thumb={thumb} active={list.some((x) => x.id === e.id)} onClick={() => toggle(e.id)} />
        ))}
      </div>
      {list.length > 0 && (
        <div className="mt-3 space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Applied ({list.length}/{MAX_EFFECTS})</h3>
          {list.map((e) => {
            const def = EFFECTS.find((d) => d.id === e.id)!;
            return (
              <div key={e.id} className="rounded-lg border border-line bg-panel2 px-2.5 py-2">
                <div className="flex items-center justify-between text-xs">
                  <span>{def.label}</span>
                  <button aria-label={`Remove ${def.label}`} onClick={() => toggle(e.id)} className="text-fg-faint hover:text-fg"><X size={13} /></button>
                </div>
                {!def.fixed && (
                  <Slider label={`${def.label} amount`} min={0} max={1} step={0.01} value={e.amount}
                    onChange={(v) => patchClips((c) => ({ ...c, effects: (c.effects ?? []).map((x) => (x.id === e.id ? { ...x, amount: v } : x)) }), `fx-${e.id}`)} />
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="mt-2 text-2xs text-fg-faint">Vignette, grain, pixelate and shake render on export; the preview shows the rest approximately.</p>
    </div>
  );
}

function TransitionsTab({ thumb, clip, patchClips }: TabProps) {
  const doc = useStore((s) => s.doc!);
  const updateDoc = useStore((s) => s.updateDoc);
  const edl = doc.edl!;
  const groups = [...new Set(TRANSITIONS.map((t) => t.group))];
  const active = clip ? clip.transitionType ?? edl.transition?.type ?? "none" : edl.transition?.type ?? "none";
  const apply = (type: string) => {
    if (clip) {
      // one boundary: the transition leading into this clip (needs a scene break before it)
      patchClips((c) => ({ ...c, transitionType: type === "none" ? null : type, sceneBreak: type === "none" ? c.sceneBreak : true }));
      if (type !== "none" && !edl.transition)
        updateDoc((d) => ({ ...d, settings: { ...d.settings, transitions: true }, edl: d.edl && { ...d.edl, transition: { type, duration: 0.5 } } }));
      return;
    }
    updateDoc((d) => ({
      ...d,
      settings: { ...d.settings, transitions: type !== "none" },
      edl: d.edl && { ...d.edl, transition: type === "none" ? null : { type, duration: d.edl.transition?.duration ?? 0.5 }, clips: d.edl.clips.map((c) => ({ ...c, transitionType: null })) },
    }));
  };
  const first = clip && edl.clips[0]?.id === clip.id;
  return (
    <div className="px-4 pb-4">
      {first && <p className="mb-2 rounded-lg border border-line bg-panel2 px-2.5 py-2 text-2xs text-fg-muted">The first clip has nothing before it. Select a later clip to set its entry transition.</p>}
      <button
        onClick={() => apply("none")}
        className={cx("mb-2 flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-xs", active === "none" ? "border-primary" : "border-line hover:border-[#4A5160]")}
      >
        <Ban size={13} /> None (hard cut)
      </button>
      {groups.map((g) => (
        <div key={g} className="mb-3">
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">{g}</h3>
          <div className="grid grid-cols-3 gap-1.5">
            {TRANSITIONS.filter((t) => t.group === g).map((t) => (
              <TransitionTile key={t.value} type={t.value} label={t.label} thumb={thumb} active={active === t.value} onClick={() => apply(t.value)} />
            ))}
          </div>
        </div>
      ))}
      <Field label="Duration" hint={`${(edl.transition?.duration ?? 0.5).toFixed(2)}s`}>
        <div className="w-32">
          <Slider label="Transition duration" min={0.1} max={2} step={0.05} value={edl.transition?.duration ?? 0.5} disabled={!edl.transition}
            onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl?.transition ? { ...d.edl, transition: { ...d.edl.transition, duration: v } } : d.edl }), { coalesce: "trdur" })} />
        </div>
      </Field>
      <p className="mt-1 text-2xs text-fg-faint">Duration is shared by all transitions and shortened to fit short clips. Hover a tile to preview.</p>
    </div>
  );
}

/** Tile with a looping CSS preview of the transition when hovered. */
function TransitionTile({ type, label, thumb, active, onClick }: { type: string; label: string; thumb?: string; active: boolean; onClick: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      aria-pressed={active}
      className={cx("overflow-hidden rounded-lg border text-left transition-colors", active ? "border-primary" : "border-line hover:border-[#4A5160]")}
    >
      <div className="relative aspect-video overflow-hidden bg-panel2">
        <div className="absolute inset-0 bg-gradient-to-br from-[#C26A8A] to-[#5A3C8E]" />
        {thumb ? <img src={thumb} alt="" className="absolute inset-0 h-full w-full object-cover" style={hover ? transitionStyle(type) : undefined} /> : <div className="absolute inset-0 bg-gradient-to-br from-[#4a5a78] to-[#2b2f38]" style={hover ? transitionStyle(type) : undefined} />}
      </div>
      <div className="truncate px-1.5 py-1 text-2xs text-fg">{label}</div>
    </button>
  );
}

/** Looping preview animation of the outgoing clip, by transition family. */
function transitionStyle(type: string): React.CSSProperties {
  const family = /^(wipe|reveal|slice|wind)/.test(type) ? "wipe" : /^(slide|smooth|cover)/.test(type) ? "slide"
    : /^(circle|radial|zoom|squeeze|vert|horz|diag|rect)/.test(type) ? "shape" : /^fadeblack|fadegrays/.test(type) ? "dip" : "fade";
  return { animation: `tr-${family} 1.1s ease-in-out infinite` };
}

import { useEffect, useRef, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { titleLook, TITLE_Y_PRESET } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { Title } from "../../types";
import { editEdl } from "../panels/shared";
import { animParams } from "./CaptionOverlay";

const ANIM_IN = { fade: 0.18, pop: 0.22, scale: 0.3, slide: 0.3 } as const;

/** Text objects drawn over the draft preview. The selected one can be dragged, resized and rotated in place. */
export function TextOverlays({ titles, time, editable }: { titles: Title[]; time: number; editable: boolean }) {
  const layer = useRef<HTMLDivElement>(null);
  const selectedId = useStore((s) => s.selectedTextId);
  const selectText = useStore((s) => s.selectText);
  const visible = titles.filter((t) => time >= t.start && time < t.start + t.duration);
  // keep the selected text on screen while editing even when the playhead is outside its time range
  const selectedOutside = editable && selectedId && !visible.some((t) => t.id === selectedId) ? titles.find((t) => t.id === selectedId) : undefined;
  const shown = selectedOutside ? [...visible, selectedOutside] : visible;

  const patch = (id: string, p: Partial<Title>, key: string) =>
    editEdl((e) => ({ ...e, titles: e.titles.map((t) => (t.id === id ? { ...t, ...p } : t)) }), key);

  const begin = (e: ReactPointerEvent, t: Title, mode: "move" | "size" | "rotate") => {
    e.stopPropagation();
    e.preventDefault();
    selectText(t.id);
    const rect = layer.current!.getBoundingClientRect();
    const look = titleLook(t);
    const cx = rect.left + look.x * rect.width, cy = rect.top + look.y * rect.height;
    const start = { x: e.clientX, y: e.clientY, tx: look.x, ty: look.y, size: look.size, dist: Math.hypot(e.clientX - cx, e.clientY - cy) };
    const move = (ev: PointerEvent) => {
      if (mode === "move") {
        const x = Math.min(1.1, Math.max(-0.1, start.tx + (ev.clientX - start.x) / rect.width));
        const y = Math.min(1.1, Math.max(-0.1, start.ty + (ev.clientY - start.y) / rect.height));
        patch(t.id, { x: Math.round(x * 1000) / 1000, y: Math.round(y * 1000) / 1000 }, `tm-${t.id}`);
      } else if (mode === "size") {
        const d = Math.hypot(ev.clientX - cx, ev.clientY - cy);
        patch(t.id, { size: Math.round(Math.min(0.5, Math.max(0.015, start.size * (d / (start.dist || 1)))) * 1000) / 1000 }, `ts-${t.id}`);
      } else {
        let deg = (Math.atan2(ev.clientY - cy, ev.clientX - cx) * 180) / Math.PI + 90;
        if (deg > 180) deg -= 360;
        for (const snap of [0, 45, 90, -45, -90, 180, -180]) if (Math.abs(deg - snap) < 4) deg = snap;
        patch(t.id, { rotation: Math.round(Math.max(-180, Math.min(180, deg))) }, `tr-${t.id}`);
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      // the click that follows a drag or tap on text must not reach the preview's play/pause handler
      const swallow = (ev: MouseEvent) => ev.stopPropagation();
      window.addEventListener("click", swallow, { capture: true, once: true });
      window.setTimeout(() => window.removeEventListener("click", swallow, { capture: true }), 0);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  useEffect(() => {
    if (!editable) return;
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (!selectedId || el.closest("input, textarea, select, [contenteditable=true]")) return;
      const step = e.shiftKey ? 0.02 : 0.005;
      const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (!d) return;
      e.preventDefault();
      const t = titles.find((x) => x.id === selectedId);
      if (t) {
        const look = titleLook(t);
        patch(t.id, { x: look.x + d[0], y: look.y + d[1] }, `tk-${t.id}`);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editable, selectedId, titles]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div ref={layer} className="pointer-events-none absolute inset-0 overflow-hidden" onPointerDown={() => editable && selectText(null)}>
      {shown.map((t) => {
        const l = titleLook(t);
        const y = t.y ?? TITLE_Y_PRESET[t.position];
        const kind = l.animation === "slide" ? "fade" : l.animation;
        const { scale, alpha } = animParams(kind, time, t.start, t.start + t.duration);
        const slide = l.animation === "slide" && time < t.start + ANIM_IN.slide ? 0.06 * (1 - (time - t.start) / ANIM_IN.slide) : 0;
        const active = editable && selectedId === t.id;
        const w = l.strokeWidth;
        const stroke = l.strokeColor;
        const style: CSSProperties = {
          position: "absolute", left: `${l.x * 100}%`, top: `${(y + Math.max(0, slide)) * 100}%`,
          transform: `translate(-50%,-50%) rotate(${l.rotation}deg) scale(${scale})`,
          fontFamily: `"${l.font}", sans-serif`, fontWeight: l.weight === "bold" ? 700 : 400, fontSize: `${l.size * 100}cqh`,
          lineHeight: 1.2, color: l.color, opacity: l.opacity * alpha, textAlign: l.align, whiteSpace: "pre-wrap",
          maxWidth: "84cqw", width: "max-content", cursor: editable ? "move" : "default", touchAction: "none",
          pointerEvents: editable ? "auto" : "none", userSelect: "none",
          ...(l.background ? { background: `${l.background}${Math.round(l.backgroundOpacity * 255).toString(16).padStart(2, "0")}`, borderRadius: "0.35em", padding: "0.55em" } : { padding: "0.55em" }),
          ...(w > 0 ? { WebkitTextStroke: `${w * 2}em ${stroke}`, paintOrder: "stroke fill" } : {}),
          ...(l.shadow ? { textShadow: "0.06em 0.06em 0.08em rgba(0,0,0,0.8)" } : {}),
          outline: active ? "1.5px dashed #508CFF" : "none", outlineOffset: "2px",
        };
        return (
          <div key={t.id} style={style} data-testid="text-overlay" onPointerDown={(e) => editable && begin(e, t, "move")} onClick={(e) => editable && e.stopPropagation()}>
            {t.text || " "}
            {active && (
              <>
                <span aria-label="Rotate text" role="slider" aria-valuenow={l.rotation} onPointerDown={(e) => begin(e, t, "rotate")} onClick={(e) => e.stopPropagation()}
                  style={{ position: "absolute", left: "50%", top: "-1.6em", width: "0.8em", height: "0.8em", transform: "translateX(-50%)", borderRadius: "50%", background: "#508CFF", cursor: "grab", boxShadow: "0 0 0 2px #fff" }} />
                <span aria-label="Resize text" role="slider" aria-valuenow={Math.round(l.size * 100)} onPointerDown={(e) => begin(e, t, "size")} onClick={(e) => e.stopPropagation()}
                  style={{ position: "absolute", right: "-0.5em", bottom: "-0.5em", width: "0.8em", height: "0.8em", borderRadius: "2px", background: "#508CFF", cursor: "nwse-resize", boxShadow: "0 0 0 2px #fff" }} />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

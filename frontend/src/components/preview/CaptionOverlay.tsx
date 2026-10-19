import type { CSSProperties } from "react";
import type { CaptionSpan } from "../../lib/layout";
import type { CaptionStyle } from "../../types";

/** Mirrors backend/rendering.py font_map and skills._anim_params so the preview matches the burned-in render. */
const FONT_SCALE = { small: 0.035, medium: 0.05, large: 0.07 } as const;
const ANIM_IN = { fade: 0.18, pop: 0.22, scale: 0.3 } as const;

export function animParams(kind: CaptionStyle["animation"], t: number, a: number, b: number): { scale: number; alpha: number } {
  if (!kind || kind === "none") return { scale: 1, alpha: 1 };
  const dIn = Math.min(ANIM_IN[kind], (b - a) / 2);
  const dOut = kind === "fade" || kind === "scale" ? Math.min(0.12, (b - a) / 4) : 0;
  let scale = 1;
  let alpha = 1;
  if (dIn > 0 && t < a + dIn) {
    const p = Math.max(0, Math.min(1, (t - a) / dIn));
    if (kind === "fade") alpha = p;
    else if (kind === "pop") {
      scale = p < 0.7 ? 0.6 + 0.52 * Math.min(1, p / 0.7) : 1.12 - (0.12 * (p - 0.7)) / 0.3;
      alpha = Math.min(1, p / 0.4);
    } else {
      scale = 0.88 + 0.12 * p;
      alpha = p;
    }
  }
  if (dOut && t > b - dOut) alpha = Math.min(alpha, Math.max(0, (b - t) / dOut));
  return { scale, alpha };
}

export function CaptionOverlay({ span, time, style, aspect }: { span: CaptionSpan; time: number; style: CaptionStyle; aspect: string }) {
  const [aw, ah] = aspect === "original" ? [16, 9] : aspect.split(":").map(Number);
  const portrait = ah > aw;
  const upper = (s: string) => (style.uppercase ? s.toUpperCase() : s);
  const words = span.words.length ? span.words : span.caption.text.split(/\s+/).filter(Boolean).map((word) => ({ word, outStart: span.outStart, outEnd: span.outEnd }));
  const active = style.karaoke && span.words.length ? words.findIndex((w) => time >= w.outStart && time < w.outEnd) : -1;
  const { scale, alpha } = animParams(style.animation, time, span.outStart, span.outEnd);
  const unit = portrait ? "cqw" : "cqh";
  const outline = style.outlineColor ?? "#000000";
  const stroke = "0.06em";
  const wrap: CSSProperties = {
    position: "absolute", left: "8%", right: "8%", textAlign: "center", pointerEvents: "none",
    ...(style.position === "top" ? { top: portrait ? "10%" : "6%" } : style.position === "center" ? { top: "50%", transform: "translateY(-50%)" } : { bottom: portrait ? "22%" : "9%" }),
  };
  const text: CSSProperties = {
    display: "inline-block", fontWeight: 700, lineHeight: 1.25, color: style.color,
    fontSize: `${FONT_SCALE[style.fontSize] * 100}${unit}`,
    transform: `scale(${scale})`, opacity: alpha,
    ...(style.background === "box" ? { background: "rgba(0,0,0,0.67)", borderRadius: "0.4em", padding: "0.25em 0.6em" } : {}),
    ...(style.background !== "none"
      ? { textShadow: `${stroke} 0 ${outline}, -${stroke} 0 ${outline}, 0 ${stroke} ${outline}, 0 -${stroke} ${outline}, ${stroke} ${stroke} ${outline}, -${stroke} -${stroke} ${outline}, ${stroke} -${stroke} ${outline}, -${stroke} ${stroke} ${outline}` }
      : {}),
  };
  return (
    <div style={wrap}>
      <span style={text} data-testid="caption-overlay">
        {words.map((w, i) => (
          <span key={i} style={i === active ? { color: style.highlightColor } : undefined}>
            {upper(w.word)}{i < words.length - 1 ? " " : ""}
          </span>
        ))}
      </span>
    </div>
  );
}

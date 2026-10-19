// Keyframe interpolation. Mirrors video_editor/keyframes.py so the preview matches the render.
import type { Keyframe } from "../types";

export const KF_PROPS = ["scale", "x", "y", "rotation", "opacity"] as const;
export type KfProp = (typeof KF_PROPS)[number];
export type KfValues = Pick<Keyframe, KfProp>;
export const KF_DEFAULTS: KfValues = { scale: 1, x: 0, y: 0, rotation: 0, opacity: 1 };

const r3 = (v: number) => Math.round(v * 1000) / 1000;

export function sortKeyframes(kfs: Keyframe[]): Keyframe[] {
  return [...kfs].sort((a, b) => a.t - b.t);
}

export function valuesAt(kfs: Keyframe[] | undefined, t: number): KfValues {
  if (!kfs?.length) return KF_DEFAULTS;
  const s = sortKeyframes(kfs);
  if (t <= s[0].t) return pick(s[0]);
  for (let i = 0; i < s.length - 1; i++) {
    const a = s[i];
    const b = s[i + 1];
    if (t < b.t) {
      let p = (t - a.t) / (b.t - a.t);
      if (a.ease === "smooth") p = p * p * (3 - 2 * p);
      const out = {} as KfValues;
      for (const k of KF_PROPS) out[k] = a[k] + (b[k] - a[k]) * p;
      return out;
    }
  }
  return pick(s[s.length - 1]);
}

const pick = (k: Keyframe): KfValues => ({ scale: k.scale, x: k.x, y: k.y, rotation: k.rotation, opacity: k.opacity });

export const isAnimated = (kfs?: Keyframe[]) => !!kfs?.some((k) => KF_PROPS.some((p) => Math.abs(k[p] - KF_DEFAULTS[p]) > 1e-9));

/** Add a keyframe at `t` holding the clip's current animated values (or replace one within 50 ms). */
export function addKeyframe(kfs: Keyframe[] | undefined, t: number, duration: number): Keyframe[] {
  const at = r3(Math.min(Math.max(0, t), duration));
  const cur = valuesAt(kfs, at);
  const rest = (kfs ?? []).filter((k) => Math.abs(k.t - at) > 0.05);
  return sortKeyframes([...rest, { t: at, ...cur, ease: "linear" }]);
}

export function updateKeyframe(kfs: Keyframe[], index: number, patch: Partial<Keyframe>): Keyframe[] {
  return sortKeyframes(kfs.map((k, i) => (i === index ? { ...k, ...patch } : k)));
}

/** CSS for the preview: the video box is moved/scaled/rotated inside the (clipped) frame. */
export function keyframeStyle(v: KfValues): { transform: string; opacity: number } {
  return {
    transform: `translate(${v.x * 100}%, ${v.y * 100}%) rotate(${v.rotation}deg) scale(${v.scale})`,
    opacity: v.opacity,
  };
}

export function fmtTime(sec: number, withFrac = false): string {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  const base = `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  if (!withFrac) return base;
  return `${base}.${String(Math.floor((sec % 1) * 10))}`;
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec == null) return "–";
  if (sec < 60) return `${sec.toFixed(1)}s`;
  return fmtTime(sec);
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

export function fmtAgo(ts: number): string {
  const d = Date.now() / 1000 - ts;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export const uid = (prefix = "") => prefix + Math.random().toString(36).slice(2, 10);

/** Deterministic JSON (sorted keys) for comparing documents. */
export function stableStringify(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(",")}]`;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return `{${Object.keys(o)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stableStringify(o[k])}`)
      .join(",")}}`;
  }
  return JSON.stringify(v);
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

export const aspectDims = (aspect: string, shortEdge: number): [number, number] => {
  const [a, b] = aspect.split(":").map(Number);
  const even = (x: number) => Math.round(x / 2) * 2;
  return a >= b ? [even((shortEdge * a) / b), shortEdge] : [shortEdge, even((shortEdge * b) / a)];
};

/** Key of the parts of an EDL that affect the rendered video (labels, scores and notes do not). */
export function renderKey(edl: unknown): string {
  if (!edl || typeof edl !== "object") return "";
  const e = edl as Record<string, any>;
  return stableStringify({
    ...e,
    notes: null,
    clips: (e.clips ?? []).map((c: Record<string, unknown>) => ({ ...c, label: null, score: null })),
  });
}

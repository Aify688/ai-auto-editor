import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";

/* ------------------------------------------------------------------ shared helpers */
const peaksCache = new Map<string, Promise<number[]>>();
export function usePeaks(url?: string) {
  const [peaks, setPeaks] = useState<number[] | null>(null);
  useEffect(() => {
    if (!url) return setPeaks(null);
    if (!peaksCache.has(url)) peaksCache.set(url, api.peaks(url).catch(() => []));
    let alive = true;
    peaksCache.get(url)!.then((p) => alive && setPeaks(p));
    return () => {
      alive = false;
    };
  }, [url]);
  return peaks;
}

export function Waveform({ peaks, step, from, seconds, pps, loop, color }: {
  peaks: number[]; step: number; from: number; seconds: number; pps: number; loop?: number; color: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const width = Math.max(1, Math.min(16000, Math.round(seconds * pps)));
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const h = cv.clientHeight || 24;
    const dpr = window.devicePixelRatio || 1;
    cv.width = width * dpr;
    cv.height = h * dpr;
    const ctx = cv.getContext("2d")!;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, h);
    ctx.fillStyle = color;
    for (let x = 0; x < width; x += 2) {
      let t = from + (x / width) * seconds;
      if (loop) t %= loop;
      const v = peaks[Math.floor(t / step)] ?? 0;
      const bh = Math.max(1, v * (h - 2));
      ctx.fillRect(x, (h - bh) / 2, 1.4, bh);
    }
  }, [peaks, step, from, seconds, width, loop, color]);
  return <canvas ref={ref} style={{ width, height: "100%" }} className="block" />;
}


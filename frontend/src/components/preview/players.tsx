// Video players for the preview panel. Edit-mode players read/write the shared store time so the
// timeline playhead and the picture stay in sync; the source player keeps its own clock.
import { useEffect, useMemo, useRef } from "react";
import { captionSpans, cropOffset, type Layout } from "../../lib/layout";
import { LOOKS } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { Edl, Media } from "../../types";

export interface Clock {
  time: number;
  duration: number;
}

function useRaf(active: boolean, fn: () => void) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (!active) return;
    let id = 0;
    const loop = () => {
      ref.current();
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, [active]);
}

/* ------------------------------------------------------------------ rendered output */
export function RenderedPlayer({ url, volume }: { url: string; volume: number }) {
  const v = useRef<HTMLVideoElement>(null);
  const playing = useStore((s) => s.playing);
  const seekNonce = useStore((s) => s.seekNonce);

  useEffect(() => {
    const video = v.current;
    if (!video) return;
    const t = useStore.getState().time;
    if (Math.abs(video.currentTime - t) > 0.04) video.currentTime = t;
  }, [seekNonce, url]);

  useEffect(() => {
    const video = v.current;
    if (!video) return;
    if (playing) {
      if (video.duration && video.currentTime >= video.duration - 0.05) video.currentTime = 0;
      video.play().catch(() => useStore.getState().setPlaying(false));
    } else video.pause();
  }, [playing]);

  useEffect(() => {
    if (v.current) v.current.volume = volume;
  }, [volume]);

  useRaf(playing, () => {
    const video = v.current;
    if (video && !video.seeking) useStore.getState().setTime(video.currentTime);
  });

  return (
    <video
      ref={v}
      src={url}
      playsInline
      preload="auto"
      className="h-full w-full bg-black object-contain"
      onEnded={() => useStore.getState().setPlaying(false)}
      onLoadedMetadata={(e) => {
        const t = useStore.getState().time;
        if (t > 0 && t < e.currentTarget.duration) e.currentTarget.currentTime = t;
      }}
    />
  );
}

/* ------------------------------------------------------------------ live draft of the EDL */
export function DraftPlayer({ edl, lay, media, volume }: { edl: Edl; lay: Layout; media: Record<string, Media>; volume: number }) {
  const v = useRef<HTMLVideoElement>(null);
  const music = useRef<HTMLAudioElement>(null);
  const cur = useRef(-1);
  const switching = useRef(false);
  const playing = useStore((s) => s.playing);
  const seekNonce = useStore((s) => s.seekNonce);
  const time = useStore((s) => s.time);
  const musicMedia = edl.music ? media[edl.music.mediaId] : undefined;
  const look = LOOKS.find((l) => l.value === edl.look)?.css ?? "none";

  const style = useMemo(() => {
    const lc = lay.clips[Math.max(0, cur.current)] ?? lay.clips[0];
    const m = lc && media[lc.clip.mediaId];
    if (!lc || !m || edl.fit === "blur") return { objectFit: "contain" as const, filter: look };
    const [ox, oy] = cropOffset(lc.clip.focusX, lc.clip.focusY, m.width ?? 16, m.height ?? 9, edl.aspect);
    return { objectFit: "cover" as const, objectPosition: `${ox * 100}% ${oy * 100}%`, filter: look };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay, media, edl.fit, edl.aspect, look, time]);

  const load = (i: number, offset: number, autoplay: boolean) => {
    const video = v.current;
    const lc = lay.clips[i];
    const m = lc && media[lc.clip.mediaId];
    if (!video || !lc || !m?.info.proxyUrl) return;
    cur.current = i;
    const target = lc.clip.srcStart + Math.max(0, offset);
    const apply = () => {
      video.currentTime = target;
      switching.current = false;
      if (autoplay) video.play().catch(() => useStore.getState().setPlaying(false));
    };
    switching.current = true;
    if (video.dataset.src !== m.info.proxyUrl) {
      video.dataset.src = m.info.proxyUrl;
      video.src = m.info.proxyUrl;
      video.addEventListener("loadedmetadata", apply, { once: true });
    } else apply();
  };

  const syncMusic = (t: number, play: boolean) => {
    const a = music.current;
    if (!a || !musicMedia?.duration) return;
    const want = t % musicMedia.duration;
    if (Math.abs(a.currentTime - want) > 0.25) a.currentTime = want;
    if (play && a.paused) a.play().catch(() => undefined);
    if (!play && !a.paused) a.pause();
  };

  // seek (also runs when the edit itself changes)
  useEffect(() => {
    const t = Math.min(useStore.getState().time, lay.duration);
    let idx = 0;
    lay.clips.forEach((lc, i) => {
      if (t >= lc.outStart) idx = i;
    });
    if (lay.clips[idx]) load(idx, t - lay.clips[idx].outStart, useStore.getState().playing);
    syncMusic(t, useStore.getState().playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seekNonce, lay]);

  useEffect(() => {
    const video = v.current;
    if (!video) return;
    if (playing) {
      if (useStore.getState().time >= lay.duration - 0.05) {
        useStore.getState().seek(0);
        return;
      }
      if (!switching.current) video.play().catch(() => useStore.getState().setPlaying(false));
    } else video.pause();
    syncMusic(useStore.getState().time, playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  useEffect(() => {
    if (v.current) v.current.volume = volume;
    if (music.current) music.current.volume = Math.min(1, volume * (edl.music?.volume ?? 0.3));
  }, [volume, edl.music?.volume]);

  useRaf(playing, () => {
    const video = v.current;
    const i = cur.current;
    const lc = lay.clips[i];
    if (!video || !lc || switching.current || video.seeking) return;
    const t = lc.outStart + (video.currentTime - lc.clip.srcStart);
    const next = lay.clips[i + 1];
    if (next && t >= next.outStart) {
      load(i + 1, t - next.outStart, true);
    } else if (!next && (t >= lc.outEnd - 0.03 || video.ended)) {
      useStore.getState().setTime(lay.duration);
      useStore.getState().setPlaying(false);
      return;
    }
    useStore.getState().setTime(Math.max(0, t));
    syncMusic(t, true);
  });

  const spans = useMemo(() => (edl.burnCaptions ? captionSpans(edl.captions, lay.clips) : []), [edl.captions, edl.burnCaptions, lay]);
  const caption = spans.find((s) => time >= s.outStart && time < s.outEnd);
  const titles = edl.titles.filter((t) => time >= t.start && time < t.start + t.duration);

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {edl.fit === "blur" && <div className="absolute inset-0 bg-black" />}
      <video ref={v} playsInline preload="auto" muted={false} className="relative h-full w-full" style={style} />
      {musicMedia?.info.url && <audio ref={music} src={musicMedia.info.url} preload="auto" loop />}
      {titles.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-none absolute inset-x-[6%] text-center ${t.position === "top" ? "top-[12%]" : t.position === "bottom" ? "bottom-[12%]" : "top-1/2 -translate-y-1/2"}`}
        >
          <span className="inline-block rounded-md bg-black/65 px-3 py-1.5 text-[clamp(14px,4.5cqh,40px)] font-bold leading-tight text-white">{t.text}</span>
        </div>
      ))}
      {caption && (
        <div className={`pointer-events-none absolute inset-x-[8%] text-center ${edl.aspect === "9:16" ? "bottom-[22%]" : "bottom-[9%]"}`}>
          <span className="inline-block rounded bg-black/65 px-2 py-1 text-[clamp(11px,3.4cqh,30px)] font-bold leading-snug text-white [text-shadow:0_1px_2px_#000]">
            {caption.caption.text}
          </span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ source media */
export function SourcePlayer({
  m, volume, seek, onClock,
}: { m: Media; volume: number; seek: { t: number; n: number }; onClock: (c: Clock) => void }) {
  const v = useRef<HTMLVideoElement>(null);
  const playing = useStore((s) => s.playing);
  const url = m.kind === "audio" ? m.info.url : m.info.proxyUrl;

  useEffect(() => {
    const video = v.current;
    if (!video) return;
    if (playing) {
      if (video.ended) video.currentTime = 0;
      video.play().catch(() => useStore.getState().setPlaying(false));
    } else video.pause();
  }, [playing, url]);

  useEffect(() => {
    if (v.current) v.current.volume = volume;
  }, [volume]);

  useEffect(() => {
    const video = v.current;
    if (video && seek.n) video.currentTime = seek.t;
  }, [seek]);

  useRaf(playing, () => {
    const video = v.current;
    if (video) onClock({ time: video.currentTime, duration: video.duration || m.duration || 0 });
  });

  if (m.kind === "image") return <img src={m.info.url} alt={m.name} className="h-full w-full bg-black object-contain" />;

  return (
    <div className="relative h-full w-full bg-black">
      <video
        ref={v}
        key={url}
        src={url}
        playsInline
        preload="auto"
        poster={m.info.thumbUrl}
        className="h-full w-full object-contain"
        onLoadedMetadata={(e) => onClock({ time: 0, duration: e.currentTarget.duration })}
        onSeeked={(e) => onClock({ time: e.currentTarget.currentTime, duration: e.currentTarget.duration })}
        onEnded={() => useStore.getState().setPlaying(false)}
      />
    </div>
  );
}

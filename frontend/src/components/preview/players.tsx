// Video players for the preview panel. Edit-mode players read/write the shared store time so the
// timeline playhead and the picture stay in sync; the source player keeps its own clock.
import { useEffect, useMemo, useRef } from "react";
import { clipFilterCss, clipFlip, hasVignette } from "../../lib/effects";
import { isAnimated, keyframeStyle, valuesAt } from "../../lib/keyframes";
import { captionSpans, clipRate, cropOffset, type Layout } from "../../lib/layout";
import { DEFAULT_CAPTION_STYLE } from "../../lib/styles";
import { audioLength } from "../../lib/timelineOps";
import { useLibrary } from "../../hooks/useLibrary";
import { CaptionOverlay } from "./CaptionOverlay";
import { TextOverlays } from "./TextOverlays";
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
  const audios = useRef<Record<string, HTMLAudioElement | null>>({});
  const library = useLibrary();
  const cur = useRef(-1);
  const switching = useRef(false);
  const freezeClock = useRef<{ base: number; wall: number } | null>(null);
  const playing = useStore((s) => s.playing);
  const seekNonce = useStore((s) => s.seekNonce);
  const time = useStore((s) => s.time);
  const clipSrc = (mediaId: string) => media[mediaId]?.info.url ?? library.find((t) => t.id === mediaId)?.url;
  const clipDur = (mediaId: string) => media[mediaId]?.duration ?? library.find((t) => t.id === mediaId)?.duration ?? undefined;
  const look = LOOKS.find((l) => l.value === edl.look)?.css ?? "none";

  const style = useMemo(() => {
    const lc = lay.clips[Math.max(0, cur.current)] ?? lay.clips[0];
    const m = lc && media[lc.clip.mediaId];
    const anim: { transform?: string; opacity?: number } = lc && isAnimated(lc.clip.keyframes) ? keyframeStyle(valuesAt(lc.clip.keyframes, time - lc.outStart)) : {};
    const fxCss = lc ? clipFilterCss(lc.clip.filter, lc.clip.effects) : "";
    const flip = lc ? clipFlip(lc.clip.effects) : "";
    const filter = [look === "none" ? "" : look, fxCss].filter(Boolean).join(" ") || "none";
    const withFlip = flip ? { ...anim, transform: `${anim.transform ?? ""} ${flip}`.trim() } : anim;
    if (!lc || !m || edl.fit === "blur") return { objectFit: "contain" as const, filter, ...withFlip };
    const [ox, oy] = cropOffset(lc.clip.focusX, lc.clip.focusY, m.width ?? 16, m.height ?? 9, edl.aspect);
    return { objectFit: "cover" as const, objectPosition: `${ox * 100}% ${oy * 100}%`, filter, ...withFlip };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay, media, edl.fit, edl.aspect, look, time]);

  const load = (i: number, offset: number, autoplay: boolean) => {
    const video = v.current;
    const lc = lay.clips[i];
    const m = lc && media[lc.clip.mediaId];
    if (!video || !lc || !m?.info.proxyUrl) return;
    cur.current = i;
    const frozen = !!lc.clip.freeze;
    const rate = clipRate(lc.clip);
    const target = lc.clip.srcStart + (frozen ? 0 : Math.max(0, offset) * rate);
    // a freeze frame is held by a wall clock: the video sits on its first frame while the timeline time advances
    freezeClock.current = frozen ? { base: lc.outStart + Math.max(0, offset), wall: performance.now() } : null;
    const apply = () => {
      video.currentTime = target;
      video.volume = Math.min(1, volumeRef.current * (lc.clip.volume ?? 1));
      video.playbackRate = frozen ? 1 : Math.min(16, Math.max(0.0625, rate));
      switching.current = false;
      if (autoplay && !frozen) video.play().catch(() => useStore.getState().setPlaying(false));
      else if (frozen) video.pause();
    };
    switching.current = true;
    if (video.dataset.src !== m.info.proxyUrl) {
      video.dataset.src = m.info.proxyUrl;
      video.src = m.info.proxyUrl;
      video.addEventListener("loadedmetadata", apply, { once: true });
    } else apply();
  };

  /** Audio timeline in the draft preview. Uses the same placement rule as the renderer (see lib/timelineOps audioLength). */
  const syncMusic = (t: number, play: boolean) => {
    for (const c of edl.audioClips ?? []) {
      const a = audios.current[c.id];
      if (!a) continue;
      const src = clipDur(c.mediaId);
      const len = audioLength(c, src, lay.duration);
      const into = t - c.start;
      const live = len > 0 && into >= 0 && into < len;
      if (!live) {
        if (!a.paused) a.pause();
        continue;
      }
      const region = src ? Math.max(0.2, src - c.trimIn) : Infinity;
      const want = c.trimIn + (c.loop ? into % region : Math.min(into, region));
      if (Math.abs(a.currentTime - want) > 0.25) a.currentTime = want;
      const fadeIn = c.fadeIn > 0 ? Math.min(1, into / c.fadeIn) : 1;
      const fadeOut = c.fadeOut > 0 ? Math.min(1, (len - into) / c.fadeOut) : 1;
      a.volume = Math.max(0, Math.min(1, c.volume * Math.min(fadeIn, fadeOut) * volumeRef.current));
      if (play && a.paused) a.play().catch(() => undefined);
      if (!play && !a.paused) a.pause();
    }
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
      if (freezeClock.current) freezeClock.current = { base: useStore.getState().time, wall: performance.now() };
      else if (!switching.current) video.play().catch(() => useStore.getState().setPlaying(false));
    } else video.pause();
    syncMusic(useStore.getState().time, playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);

  const volumeRef = useRef(volume);
  volumeRef.current = volume;
  useEffect(() => {
    if (v.current) v.current.volume = volume;
    syncMusic(useStore.getState().time, useStore.getState().playing);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [volume, edl.audioClips]);

  useRaf(playing, () => {
    const video = v.current;
    const i = cur.current;
    const lc = lay.clips[i];
    if (!video || !lc || switching.current || video.seeking) return;
    const fz = freezeClock.current;
    const t = fz ? fz.base + (performance.now() - fz.wall) / 1000 : lc.outStart + (video.currentTime - lc.clip.srcStart) / clipRate(lc.clip);
    const next = lay.clips[i + 1];
    if (next && t >= next.outStart) {
      load(i + 1, t - next.outStart, true);
    } else if (!next && (t >= lc.outEnd - 0.03 || (!fz && video.ended))) {
      useStore.getState().setTime(lay.duration);
      useStore.getState().setPlaying(false);
      return;
    }
    useStore.getState().setTime(Math.max(0, t));
    syncMusic(t, true);
  });

  const spans = useMemo(() => (edl.burnCaptions ? captionSpans(edl.captions, lay.clips) : []), [edl.captions, edl.burnCaptions, lay]);
  const caption = spans.find((s) => time >= s.outStart && time < s.outEnd);
  const capStyle = edl.captionStyle ?? DEFAULT_CAPTION_STYLE;

  return (
    <div className="relative h-full w-full overflow-hidden bg-black">
      {edl.fit === "blur" && <div className="absolute inset-0 bg-black" />}
      <video ref={v} playsInline preload="auto" muted={false} className="relative h-full w-full" style={style} />
      {(edl.audioClips ?? []).map((c) => {
        const src = clipSrc(c.mediaId);
        return src ? <audio key={c.id} ref={(el) => { audios.current[c.id] = el; }} src={src} preload="auto" /> : null;
      })}
      {(() => {
        const vig = hasVignette(lay.clips[Math.max(0, cur.current)]?.clip.effects);
        return vig > 0 ? <div className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(ellipse at center, transparent ${70 - vig * 30}%, rgba(0,0,0,${0.35 + vig * 0.5}) 100%)` }} /> : null;
      })()}
      <TextOverlays titles={edl.titles} time={time} editable={!playing} />
      {caption && <CaptionOverlay span={caption} time={time} style={capStyle} aspect={edl.aspect} />}
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

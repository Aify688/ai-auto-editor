import { Music, Pause, Play, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ACCEPT, uploadFiles } from "../../hooks/useUpload";
import { fmtDuration } from "../../lib/format";
import { setPrimaryMusic } from "../../lib/timelineOps";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { MusicLibraryTrack, MusicMood, MusicSource } from "../../types";
import { Button, Empty, Field, PanelHeader, Segmented, Select, Slider, Toggle, cx } from "../ui/controls";
import { MusicRecommendations } from "./MusicRecommendations";
import { Voiceover } from "./Voiceover";

// Mirrors backend/services/music_library.py's _STYLE_MOOD / auto_mood(): which mood "auto" picks
// for each editing style, so the preview track and volume/duck controls update immediately instead
// of waiting for the next full regenerate. The backend is the source of truth at render time.
const AUTO_MOOD: Record<string, MusicMood> = {
  dynamic: "energetic",
  marketing: "energetic",
  social: "happy",
  vlog: "happy",
  cinematic: "cinematic",
  travel: "cinematic",
  professional: "relaxing",
};
const autoMoodFor = (style: string): MusicMood => AUTO_MOOD[style] ?? "cinematic";

const MOOD_LABEL: Record<MusicMood, string> = {
  cinematic: "Cinematic",
  energetic: "Energetic",
  relaxing: "Relaxing",
  happy: "Happy",
  dramatic: "Dramatic",
};

// UI only ever sets musicSource to "none" | "upload" | "library". The schema's "auto" value is
// equivalent to "library" with musicMood left unset (see pipeline._music_row), so there's no need
// to expose it as a separate source to choose from.
type SourceChoice = "none" | "upload" | "library";

export function AudioPanel() {
  const doc = useStore((s) => s.doc!);
  const tracks = useStore((s) => s.media.filter((m) => m.kind === "audio"));
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [library, setLibrary] = useState<MusicLibraryTrack[]>([]);
  const audio = useRef<HTMLAudioElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const st = doc.settings;
  const edl = doc.edl;
  const audioCfg = edl?.audio;

  useEffect(() => () => audio.current?.pause(), []);

  useEffect(() => {
    api
      .musicLibrary()
      .then(setLibrary)
      .catch(() => toast("Couldn't load the background-music library.", "error"));
  }, [toast]);

  const preview = (id: string, url?: string) => {
    const a = audio.current;
    if (!a || !url) return;
    if (playingId === id) {
      a.pause();
      setPlayingId(null);
      return;
    }
    a.src = url;
    a.play().then(() => setPlayingId(id)).catch(() => setPlayingId(null));
  };

  const source: SourceChoice = st.musicSource === "auto" ? "library" : st.musicSource;
  const effectiveMood = st.musicMood ?? autoMoodFor(doc.style);
  const libraryTrack = library.find((t) => t.mood === effectiveMood) ?? null;

  const musicEdl = (d: typeof doc, mediaId: string | null) =>
    d.edl && setPrimaryMusic(d.edl, mediaId ? { mediaId, volume: d.settings.musicVolume } : null);

  const chooseSource = (src: SourceChoice) =>
    updateDoc((d) => {
      if (src === "none") {
        return { ...d, settings: { ...d.settings, musicSource: "none" as MusicSource }, edl: musicEdl(d, null) };
      }
      if (src === "upload") {
        return { ...d, settings: { ...d.settings, musicSource: "upload" as MusicSource }, edl: musicEdl(d, d.settings.musicId) };
      }
      const mood = d.settings.musicMood ?? autoMoodFor(d.style);
      const track = library.find((t) => t.mood === mood);
      return { ...d, settings: { ...d.settings, musicSource: "library" as MusicSource }, edl: musicEdl(d, track?.id ?? null) };
    });

  const chooseMusic = (id: string | null) =>
    updateDoc((d) => ({ ...d, settings: { ...d.settings, musicSource: "upload" as MusicSource, musicId: id }, edl: musicEdl(d, id) }));

  const chooseMood = (mood: MusicMood | null) =>
    updateDoc((d) => {
      const effective = mood ?? autoMoodFor(d.style);
      const track = library.find((t) => t.mood === effective);
      return {
        ...d,
        settings: { ...d.settings, musicSource: "library" as MusicSource, musicMood: mood },
        edl: musicEdl(d, track?.id ?? null),
      };
    });

  return (
    <div className="flex h-full flex-col">
      <PanelHeader
        title="Audio"
        subtitle="Music, levels and voice."
        action={<Button size="sm" icon={<UploadCloud size={13} />} onClick={() => input.current?.click()}>Add music</Button>}
      />
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => { e.target.files && uploadFiles(Array.from(e.target.files)); e.target.value = ""; }} />
      <audio ref={audio} onEnded={() => setPlayingId(null)} />
      <div className="flex-1 overflow-y-auto px-4 pb-4">
        <Voiceover />
        <MusicRecommendations compact />
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Background music</h3>
        <Field label="Source">
          <Segmented
            label="Music source"
            value={source}
            options={[
              { value: "none", label: "None" },
              { value: "upload", label: "My upload" },
              { value: "library", label: "Library" },
            ]}
            onChange={chooseSource}
          />
        </Field>

        {source === "upload" && (
          tracks.length === 0 ? (
            <Empty icon={<Music size={18} />} title="No music files" text="Upload an MP3 or WAV to use as background music." />
          ) : (
            <div className="mt-2 space-y-1" role="radiogroup" aria-label="Background music">
              {tracks.map((t) => {
                const on = st.musicId === t.id;
                const ready = t.status === "ready";
                return (
                  <div
                    key={t.id}
                    role="radio"
                    aria-checked={on}
                    tabIndex={0}
                    onClick={() => ready && chooseMusic(t.id)}
                    onKeyDown={(e) => e.key === "Enter" && ready && chooseMusic(t.id)}
                    className={cx(
                      "flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 transition-colors",
                      on ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]",
                      !ready && "opacity-50",
                    )}
                  >
                    <button
                      aria-label={playingId === t.id ? "Stop preview" : "Play preview"}
                      onClick={(e) => { e.stopPropagation(); preview(t.id, t.info.url); }}
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-clip-audio text-white hover:brightness-125"
                    >
                      {playingId === t.id ? <Pause size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" className="ml-px" />}
                    </button>
                    <span className="min-w-0 flex-1 truncate text-xs text-fg">{t.name}</span>
                    {t.duration != null && <span className="text-2xs tabular-nums text-fg-faint">{fmtDuration(t.duration)}</span>}
                  </div>
                );
              })}
            </div>
          )
        )}

        {source === "library" && (
          <div className="mt-2 space-y-1" role="radiogroup" aria-label="Music mood">
            {([{ mood: null as MusicMood | null, title: "Auto · matches your style" }, ...library.map((t) => ({ mood: t.mood as MusicMood | null, title: MOOD_LABEL[t.mood] }))]).map((opt) => {
              const on = opt.mood === null ? !st.musicMood : st.musicMood === opt.mood;
              const track = opt.mood ? library.find((t) => t.mood === opt.mood) : libraryTrack;
              return (
                <div
                  key={opt.mood ?? "auto"}
                  role="radio"
                  aria-checked={on}
                  tabIndex={0}
                  onClick={() => chooseMood(opt.mood)}
                  onKeyDown={(e) => e.key === "Enter" && chooseMood(opt.mood)}
                  className={cx(
                    "flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 transition-colors",
                    on ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]",
                    !track && "opacity-50",
                  )}
                >
                  <button
                    aria-label={playingId === (track?.id ?? "") ? "Stop preview" : "Play preview"}
                    disabled={!track}
                    onClick={(e) => { e.stopPropagation(); track && preview(track.id, track.url); }}
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-clip-audio text-white hover:brightness-125 disabled:opacity-40"
                  >
                    {playingId === (track?.id ?? "") ? <Pause size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" className="ml-px" />}
                  </button>
                  <span className="min-w-0 flex-1 truncate text-xs text-fg">
                    {opt.title}
                    {opt.mood === null && <span className="ml-1 text-fg-faint">({MOOD_LABEL[effectiveMood]})</span>}
                  </span>
                  {track && <span className="text-2xs tabular-nums text-fg-faint">{fmtDuration(track.duration)}</span>}
                </div>
              );
            })}
            {library[0] && <p className="mt-1.5 text-2xs text-fg-faint">{library[0].attribution}</p>}
          </div>
        )}

        {edl?.music && (
          <div className="mt-2">
            <Field label="Music volume" hint={`${Math.round(st.musicVolume * 100)}%`}>
              <div className="w-32">
                <Slider label="Music volume" min={0.05} max={1} step={0.05} value={st.musicVolume}
                  onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, musicVolume: v }, edl: d.edl?.music ? setPrimaryMusic(d.edl, { volume: v }) : d.edl }), { coalesce: "musicvol" })} />
              </div>
            </Field>
            <Field label="Duck under speech" hint="Lowers music while people talk">
              <Toggle label="Duck under speech" checked={edl.music.duck} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl?.music ? setPrimaryMusic(d.edl, { duck: v }) : d.edl }))} />
            </Field>
          </div>
        )}

        <h3 className="mb-1 mt-5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">Levels</h3>
        <Field label="Loudness normalization">
          <Toggle label="Loudness normalization" checked={audioCfg ? audioCfg.normalize : st.normalizeAudio}
            onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, normalizeAudio: v }, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, normalize: v } } }))} />
        </Field>
        {audioCfg && (
          <>
            {audioCfg.normalize && (
              <Field label="Target loudness">
                <Select label="Target loudness" className="w-36" value={audioCfg.lufs}
                  options={[{ value: -14, label: "-14 LUFS · Social" }, { value: -16, label: "-16 LUFS · Web" }, { value: -23, label: "-23 LUFS · Broadcast" }]}
                  onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, lufs: v } } }))} />
              </Field>
            )}
            <Field label="Voice cleanup" hint="Rumble filter + noise reduction">
              <Toggle label="Voice cleanup" checked={audioCfg.clean} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, clean: v } } }))} />
            </Field>
            <Field label="Fade in / out">
              <Toggle label="Fade in and out" checked={audioCfg.fades} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl && { ...d.edl, audio: { ...d.edl.audio, fades: v } } }))} />
            </Field>
          </>
        )}
        {!edl && <p className="mt-2 text-2xs text-fg-faint">More audio options appear after you generate an edit.</p>}
      </div>
    </div>
  );
}

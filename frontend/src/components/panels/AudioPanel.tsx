import { Music, Pause, Play, UploadCloud } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ACCEPT, uploadFiles } from "../../hooks/useUpload";
import { fmtDuration } from "../../lib/format";
import { useStore } from "../../store/project";
import { Button, Empty, Field, PanelHeader, Select, Slider, Toggle, cx } from "../ui/controls";

export function AudioPanel() {
  const doc = useStore((s) => s.doc!);
  const tracks = useStore((s) => s.media.filter((m) => m.kind === "audio"));
  const updateDoc = useStore((s) => s.updateDoc);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const st = doc.settings;
  const edl = doc.edl;
  const audioCfg = edl?.audio;

  useEffect(() => () => audio.current?.pause(), []);

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

  const chooseMusic = (id: string | null) =>
    updateDoc((d) => ({
      ...d,
      settings: { ...d.settings, musicId: id },
      edl: d.edl && { ...d.edl, music: id ? { mediaId: id, volume: d.settings.musicVolume, duck: d.edl.music?.duck ?? true } : null },
    }));

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
        <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-fg-muted">Background music</h3>
        {tracks.length === 0 ? (
          <Empty icon={<Music size={18} />} title="No music files" text="Upload an MP3 or WAV to use as background music." />
        ) : (
          <div className="space-y-1" role="radiogroup" aria-label="Background music">
            {[{ id: null as string | null, name: "No music", duration: null as number | null, url: undefined as string | undefined, ready: true }, ...tracks.map((t) => ({ id: t.id as string | null, name: t.name, duration: t.duration, url: t.info.url, ready: t.status === "ready" }))].map((t) => {
              const on = st.musicId === t.id;
              return (
                <div
                  key={t.id ?? "none"}
                  role="radio"
                  aria-checked={on}
                  tabIndex={0}
                  onClick={() => t.ready && chooseMusic(t.id)}
                  onKeyDown={(e) => e.key === "Enter" && t.ready && chooseMusic(t.id)}
                  className={cx(
                    "flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 transition-colors",
                    on ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]",
                    !t.ready && "opacity-50",
                  )}
                >
                  {t.id ? (
                    <button
                      aria-label={playingId === t.id ? "Stop preview" : "Play preview"}
                      onClick={(e) => { e.stopPropagation(); preview(t.id!, t.url); }}
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-clip-audio text-white hover:brightness-125"
                    >
                      {playingId === t.id ? <Pause size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" className="ml-px" />}
                    </button>
                  ) : (
                    <span className="h-6 w-6 shrink-0" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-xs text-fg">{t.name}</span>
                  {t.duration != null && <span className="text-2xs tabular-nums text-fg-faint">{fmtDuration(t.duration)}</span>}
                </div>
              );
            })}
          </div>
        )}
        {st.musicId && (
          <div className="mt-2">
            <Field label="Music volume" hint={`${Math.round(st.musicVolume * 100)}%`}>
              <div className="w-32">
                <Slider label="Music volume" min={0.05} max={1} step={0.05} value={st.musicVolume}
                  onChange={(v) => updateDoc((d) => ({ ...d, settings: { ...d.settings, musicVolume: v }, edl: d.edl?.music ? { ...d.edl, music: { ...d.edl.music, volume: v } } : d.edl }), { coalesce: "musicvol" })} />
              </div>
            </Field>
            {edl?.music && (
              <Field label="Duck under speech" hint="Lowers music while people talk">
                <Toggle label="Duck under speech" checked={edl.music.duck} onChange={(v) => updateDoc((d) => ({ ...d, edl: d.edl?.music ? { ...d.edl, music: { ...d.edl.music, duck: v } } : d.edl }))} />
              </Field>
            )}
          </div>
        )}

        <h3 className="mb-1 mt-5 text-xs font-medium uppercase tracking-wide text-fg-muted">Levels</h3>
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

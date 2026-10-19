import { Copy, Loader2, Music4, Pause, Play, Plus, Replace, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { uploadFiles } from "../../hooks/useUpload";
import { fmtDuration } from "../../lib/format";
import { layout } from "../../lib/layout";
import { isLibraryId, musicModeOf, withAutoMusic, withChosenTrack, withoutMusic, type MusicMode } from "../../lib/music";
import { primaryMusic, setPrimaryMusic, trimAudioStart } from "../../lib/timelineOps";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { MusicLibraryTrack, MusicMood } from "../../types";
import type { MusicProviderStatus, MusicResult } from "../../types/music";
import { Button, Empty, Field, PanelHeader, Segmented, Slider, Toggle } from "../ui/controls";

// Mirrors backend music_library.auto_mood: which bundled mood Auto picks for a style until Auto-edit chooses from the footage.
const AUTO_MOOD: Record<string, MusicMood> = { dynamic: "energetic", marketing: "energetic", social: "happy", vlog: "happy", cinematic: "cinematic", travel: "cinematic", professional: "relaxing", energetic: "energetic", minimal: "relaxing", documentary: "cinematic" };

const MODES: { value: MusicMode; label: string }[] = [
  { value: "auto", label: "Auto-select music" },
  { value: "choose", label: "Choose music" },
  { value: "none", label: "No music" },
];

/** Music: let Auto-edit pick, choose a track yourself (search, upload), or none. Nothing is added until "Add to video". */
export function MusicPanel() {
  const doc = useStore((s) => s.doc);
  const project = useStore((s) => s.project);
  const media = useStore((s) => s.media);
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const audio = useRef<HTMLAudioElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MusicResult[] | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [searching, setSearching] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [providers, setProviders] = useState<MusicProviderStatus[]>([]);
  const [library, setLibrary] = useState<MusicLibraryTrack[]>([]);

  const settings = doc?.settings;
  const mode = settings ? musicModeOf(settings) : "auto";
  const edl = doc?.edl ?? null;
  const clip = edl ? primaryMusic(edl) : undefined;
  const total = useMemo(() => (edl ? layout(edl).duration : 0), [edl]);

  useEffect(() => () => audio.current?.pause(), []);
  useEffect(() => { api.musicStatus().then((s) => setProviders(s.providers)).catch(() => undefined); api.musicLibrary().then(setLibrary).catch(() => undefined); }, []);

  // search the library as the user types (and show everything when the box is empty)
  useEffect(() => {
    if (mode !== "choose") return;
    let stale = false;
    setSearching(true);
    const t = window.setTimeout(() => {
      api.musicSearch(query.trim()).then((r) => { if (!stale) { setResults(r.results); setNotices(r.notices); } })
        .catch((e) => { if (!stale) { setResults([]); setNotices([(e as Error).message]); } })
        .finally(() => { if (!stale) setSearching(false); });
    }, query ? 350 : 0);
    return () => { stale = true; window.clearTimeout(t); };
  }, [query, mode]);

  if (!doc || !settings) return <></>;

  const preview = (id: string, url: string) => {
    const a = audio.current;
    if (!a) return;
    if (playing === id) { a.pause(); setPlaying(null); return; }
    a.src = url;
    a.currentTime = 0;
    a.play().then(() => setPlaying(id)).catch(() => { setPlaying(null); toast("Could not play the preview.", "error"); });
  };

  const setMode = (m: MusicMode) => {
    audio.current?.pause();
    setPlaying(null);
    if (m === "none") updateDoc((d) => withoutMusic(d));
    else if (m === "auto") {
      const mood = AUTO_MOOD[doc.style] ?? "cinematic";
      updateDoc((d) => withAutoMusic(d, library.find((t) => t.mood === mood)?.id ?? `lib:${mood}`));
    } else updateDoc((d) => ({ ...d, settings: { ...d.settings, musicMode: "choose" } }));   // choose: nothing added yet
  };

  const addTrack = async (mediaId: string) => {
    audio.current?.pause();
    setPlaying(null);
    updateDoc((d) => withChosenTrack(d, mediaId));
    toast(clip ? "Music replaced." : "Music added to your video.", "success");
  };

  const addResult = async (r: MusicResult) => {
    if (!project || adding) return;
    setAdding(r.id);
    try {
      const res = await api.addMusic(project.id, r.id);
      if (res.media) {
        useStore.getState().setMedia([...useStore.getState().media.filter((m) => m.id !== res.media!.id), res.media]);
        for (let i = 0; i < 60; i++) {                       // wait for the waveform/duration to be ready
          const m = useStore.getState().media.find((x) => x.id === res.mediaId);
          if (m && m.status !== "processing") break;
          await new Promise((ok) => setTimeout(ok, 500));
          await useStore.getState().refreshMedia();
        }
      }
      await addTrack(res.mediaId);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setAdding(null);
    }
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    await uploadFiles(Array.from(files).filter((f) => /\.(mp3|wav)$/i.test(f.name)));
  };

  const uploads = media.filter((m) => m.kind === "audio" && !m.name.startsWith("Voiceover - ") && !m.info.attribution);
  const currentName = clip
    ? isLibraryId(clip.mediaId) ? library.find((t) => t.id === clip.mediaId)?.title ?? "Library track"
      : media.find((m) => m.id === clip.mediaId)?.info.attribution?.title ?? media.find((m) => m.id === clip.mediaId)?.name ?? "Your track"
    : null;
  const currentAttribution = clip
    ? isLibraryId(clip.mediaId) ? library.find((t) => t.id === clip.mediaId)?.attribution : media.find((m) => m.id === clip.mediaId)?.info.attribution?.text
    : null;
  const srcDur = clip ? (isLibraryId(clip.mediaId) ? library.find((t) => t.id === clip.mediaId)?.duration : media.find((m) => m.id === clip.mediaId)?.duration) ?? undefined : undefined;
  const maxFade = Math.max(0.1, Math.min(10, ((clip?.duration ?? total) || 4) / 2));

  const patchMusic = (p: Partial<NonNullable<typeof clip>>, key: string) =>
    updateDoc((d) => (d.edl ? { ...d, settings: p.volume != null ? { ...d.settings, musicVolume: Math.max(0.02, p.volume) } : d.settings, edl: setPrimaryMusic(d.edl, p) } : d), { coalesce: `music-${key}` });

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Music" subtitle="Background music for your video." action={<Button size="sm" icon={<Upload size={13} />} onClick={() => fileInput.current?.click()}>Upload audio</Button>} />
      <input ref={fileInput} type="file" accept=".mp3,.wav" multiple hidden onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
      <audio ref={audio} onEnded={() => setPlaying(null)} />
      <div className="flex-1 space-y-4 overflow-y-auto px-4 pb-4">
        <Segmented label="Music mode" value={mode} options={MODES} onChange={setMode} />
        <p className="-mt-2 text-2xs text-fg-faint">
          {mode === "auto" && "Auto-edit picks a track that suits your footage and style. It is lowered while people speak."}
          {mode === "choose" && "Search below or use your own file. Auto-edit keeps the track you add."}
          {mode === "none" && "Your video has no background music. Auto-edit will not add any."}
        </p>

        {clip && mode !== "none" && (
          <section className="rounded-xl border border-line bg-panel2 px-3 py-3" aria-label="Your music">
            <div className="flex items-center gap-2">
              <Music4 size={15} className="shrink-0 text-clip-audio" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold text-fg">{currentName}</div>
                <div className="text-2xs text-fg-faint">{mode === "auto" ? "Auto-selected" : "Added by you"} · {fmtDuration(srcDur ?? 0)}</div>
              </div>
            </div>
            <div className="mt-3 space-y-2.5">
              <div>
                <div className="mb-1 flex justify-between text-xs"><span>Volume</span><span className="tabular-nums text-fg-muted">{Math.round(clip.volume * 100)}%</span></div>
                <Slider label="Music volume" min={0.02} max={1} step={0.01} value={clip.volume} onChange={(v) => patchMusic({ volume: v }, "vol")} />
              </div>
              <Field label="Lower during speech" hint="Keeps dialogue clear">
                <Toggle label="Lower music during speech" checked={clip.duck} onChange={(v) => patchMusic({ duck: v }, "duck")} />
              </Field>
              <div>
                <div className="mb-1 flex justify-between text-xs"><span>Starts at</span><span className="tabular-nums text-fg-muted">{clip.start.toFixed(1)}s</span></div>
                <Slider label="Music start" min={0} max={Math.max(0.1, total - 0.5)} step={0.1} value={Math.min(clip.start, Math.max(0.1, total - 0.5))} onChange={(v) => patchMusic({ start: v }, "start")} />
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs"><span>Trim: start the song at</span><span className="tabular-nums text-fg-muted">{clip.trimIn.toFixed(1)}s</span></div>
                <Slider label="Trim start of song" min={0} max={Math.max(0.1, (srcDur ?? 60) - 1)} step={0.1} value={Math.min(clip.trimIn, Math.max(0.1, (srcDur ?? 60) - 1))}
                  onChange={(v) => patchMusic(trimAudioStart(clip, v - clip.trimIn, { total, pps: 100, points: [], srcDur, others: [] }).clip, "trim")} />
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs"><span>Fade in</span><span className="tabular-nums text-fg-muted">{clip.fadeIn.toFixed(1)}s</span></div>
                <Slider label="Music fade in" min={0} max={maxFade} step={0.1} value={Math.min(clip.fadeIn, maxFade)} onChange={(v) => patchMusic({ fadeIn: v }, "fi")} />
              </div>
              <div>
                <div className="mb-1 flex justify-between text-xs"><span>Fade out</span><span className="tabular-nums text-fg-muted">{clip.fadeOut.toFixed(1)}s</span></div>
                <Slider label="Music fade out" min={0} max={maxFade} step={0.1} value={Math.min(clip.fadeOut, maxFade)} onChange={(v) => patchMusic({ fadeOut: v }, "fo")} />
              </div>
            </div>
            <div className="mt-3 flex gap-2">
              <Button size="sm" className="flex-1" icon={<Replace size={12} />} onClick={() => { setMode("choose"); }}>Replace</Button>
              <Button size="sm" variant="danger" className="flex-1" icon={<Trash2 size={12} />} onClick={() => updateDoc((d) => withoutMusic(d))}>Remove</Button>
            </div>
            {currentAttribution && (
              <div className="mt-3 rounded-lg border border-line bg-app p-2 text-2xs text-fg-muted">
                <div className="mb-1 font-semibold text-fg">Credit required</div>
                <p className="break-words">{currentAttribution}</p>
                <button className="mt-1 inline-flex items-center gap-1 text-primary hover:underline" onClick={() => { void navigator.clipboard?.writeText(currentAttribution); toast("Credit copied."); }}><Copy size={10} /> Copy credit</button>
                <p className="mt-1 text-fg-faint">Export also writes this to a .credits.txt file next to your video.</p>
              </div>
            )}
          </section>
        )}
        {mode === "auto" && !clip && <p className="rounded-lg border border-line bg-panel2 p-2.5 text-2xs text-fg-muted">Run Auto-edit to add music that fits your footage.</p>}

        {mode === "choose" && (
          <>
            <div className="relative">
              <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" />
              <input aria-label="Search music" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search title, artist, genre or mood"
                className="h-9 w-full rounded-lg border border-line bg-app pl-8 pr-2 text-xs text-fg outline-none focus:border-primary" />
            </div>
            {providers.find((p) => p.id === "jamendo" && !p.configured) && (
              <div className="rounded-lg border border-warn/40 bg-warn/10 p-2.5 text-2xs text-warn" role="status">{providers.find((p) => p.id === "jamendo")?.hint}</div>
            )}
            {notices.filter((n) => !n.startsWith("Search for more music")).map((n) => <p key={n} className="text-2xs text-fg-faint">{n}</p>)}
            {searching && !results ? <div className="flex items-center gap-2 text-xs text-fg-muted"><Loader2 size={13} className="animate-spin" /> Searching…</div> : null}
            {results && results.length === 0 && !searching && <Empty icon={<Music4 size={18} />} title="No tracks found" text="Try a genre such as pop or a mood such as calm." />}
            <ul className="space-y-1.5" aria-label="Search results">
              {results?.map((r) => (
                <li key={r.id} className="rounded-lg border border-line bg-panel2 p-2">
                  <div className="flex items-center gap-2">
                    <button aria-label={playing === r.id ? `Pause ${r.title}` : `Preview ${r.title}`} onClick={() => preview(r.id, r.previewUrl)}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-clip-audio text-white hover:brightness-125">
                      {playing === r.id ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" className="ml-px" />}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-fg">{r.title}</div>
                      <div className="truncate text-2xs text-fg-muted">{r.artist} · {fmtDuration(r.duration)}</div>
                    </div>
                    <Button size="sm" variant="primary" disabled={!!adding} icon={adding === r.id ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} onClick={() => void (isLibraryId(r.id) ? addTrack(r.id) : addResult(r))}>
                      {adding === r.id ? "Adding…" : "Add to video"}
                    </Button>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1 text-2xs text-fg-faint">
                    {[...r.genres, ...r.moods].slice(0, 3).map((t) => <span key={t} className="rounded bg-app px-1.5 py-0.5">{t}</span>)}
                    <a href={r.license.url ?? undefined} target="_blank" rel="noreferrer" className="ml-auto text-fg-muted underline-offset-2 hover:underline" title="Licence">{r.license.label}</a>
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-2xs text-fg-faint">Only tracks you may use in videos you publish are listed. Each needs a credit, which Export writes to a .credits.txt file.</p>

            <h3 className="pt-1 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">My audio files</h3>
            {uploads.length === 0 ? (
              <p className="text-2xs text-fg-faint">Upload an MP3 or WAV with the button above. Use music you own or have the right to use.</p>
            ) : (
              <ul className="space-y-1.5" aria-label="My audio files">
                {uploads.map((m) => (
                  <li key={m.id} className="flex items-center gap-2 rounded-lg border border-line bg-panel2 p-2">
                    <button aria-label={playing === m.id ? `Pause ${m.name}` : `Preview ${m.name}`} disabled={m.status !== "ready"} onClick={() => m.info.url && preview(m.id, m.info.url)}
                      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-clip-audio text-white hover:brightness-125 disabled:opacity-40">
                      {playing === m.id ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" className="ml-px" />}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-fg">{m.name.replace(/\.[^.]+$/, "")}</div>
                      <div className="text-2xs text-fg-muted">{m.status === "processing" ? "Processing…" : m.duration ? fmtDuration(m.duration) : ""}</div>
                    </div>
                    <Button size="sm" variant="primary" disabled={m.status !== "ready"} icon={<Plus size={12} />} onClick={() => void addTrack(m.id)}>Add to video</Button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}

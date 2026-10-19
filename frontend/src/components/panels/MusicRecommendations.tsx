import { AlertTriangle, Heart, Music, Pause, Play, RotateCw, VolumeX } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { MusicRecommendations as Reco } from "../../types";
import { setPrimaryMusic } from "../../lib/timelineOps";
import { Button, cx } from "../ui/controls";

const FAV_KEY = "frameflow.favoriteTracks";
const loadFavs = (): string[] => {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) ?? "[]"); } catch { return []; }
};

/** Three licensed library tracks that suit the footage, each with a reason. Preview, apply/replace, favourite, or no music. */
export function MusicRecommendations({ compact = false }: { compact?: boolean }) {
  const project = useStore((s) => s.project);
  const edl = useStore((s) => s.doc?.edl ?? null);
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const [data, setData] = useState<Reco | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [playing, setPlaying] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(loadFavs);
  const audio = useRef<HTMLAudioElement>(null);
  const hasEdit = !!edl?.clips.length;

  useEffect(() => {
    if (!project || !hasEdit) return;
    let alive = true;
    setError(null);
    setData(null);
    api
      .musicRecommendations(project.id)
      .then((r) => alive && setData(r))
      .catch((e: Error) => alive && setError(e.message || "Could not load music recommendations."));
    return () => { alive = false; };
  }, [project?.id, hasEdit, edl?.plan?.instruction, attempt]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => () => audio.current?.pause(), []);

  if (!hasEdit) return null;
  const current = edl?.music?.mediaId ?? null;

  const preview = (t: Reco["tracks"][number]) => {
    const a = audio.current;
    if (!a) return;
    if (playing === t.id) { a.pause(); setPlaying(null); return; }
    a.src = t.url;
    a.currentTime = 0;
    a.play().then(() => setPlaying(t.id)).catch(() => toast("Could not play the preview.", "error"));
  };
  const apply = (t: Reco["tracks"][number]) => {
    updateDoc((d) => d.edl ? {
      ...d,
      settings: { ...d.settings, musicMode: "choose", musicSource: "library", musicMood: t.mood, musicId: null, musicVolume: t.suggestedVolume },
      edl: setPrimaryMusic(d.edl, { mediaId: t.id, volume: t.suggestedVolume }),
    } : d);
    toast(`"${t.title}" ${current ? "replaced the music" : "added"}. Render a preview to hear it.`, "success");
  };
  const none = () => {
    updateDoc((d) => d.edl ? { ...d, settings: { ...d.settings, musicMode: "none", musicSource: "none", musicId: null }, edl: setPrimaryMusic(d.edl, null) } : d);
  };
  const favourite = (id: string) => {
    const next = favs.includes(id) ? favs.filter((f) => f !== id) : [...favs, id];
    setFavs(next);
    try { localStorage.setItem(FAV_KEY, JSON.stringify(next)); } catch { /* storage unavailable: favourites last for this session only */ }
  };
  const ordered = data ? [...data.tracks].sort((a, b) => Number(favs.includes(b.id)) - Number(favs.includes(a.id))) : null;

  return (
    <section className={cx("rounded-xl border border-line bg-panel2 p-3", compact && "mb-4")}>
      <audio ref={audio} onEnded={() => setPlaying(null)} />
      <div className="mb-2 flex items-center justify-between">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted"><Music size={12} /> Recommended music</h3>
        <Button size="sm" variant="ghost" disabled={!current} icon={<VolumeX size={12} />} onClick={none}>No music</Button>
      </div>
      {error && (
        <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 p-2.5">
          <div className="flex gap-2 text-xs text-danger"><AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>Music recommendations are not available right now. {error}</span></div>
          <Button size="sm" className="mt-2" icon={<RotateCw size={12} />} onClick={() => setAttempt((n) => n + 1)}>Retry</Button>
        </div>
      )}
      {!ordered && !error && <p className="text-2xs text-fg-faint">Matching music to your footage…</p>}
      {data?.basis === "style" && <p className="mb-2 text-2xs text-fg-faint">Based on your editing style. Generate an edit once to match the footage itself.</p>}
      <ul className="space-y-2">
        {ordered?.map((t) => {
          const active = current === t.id;
          return (
            <li key={t.id} className={cx("rounded-lg border px-2.5 py-2", active ? "border-primary bg-primary-muted" : "border-line bg-panel")}>
              <div className="flex items-center gap-2">
                <button aria-label={playing === t.id ? `Pause ${t.title}` : `Preview ${t.title}`} onClick={() => preview(t)}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-raise text-fg hover:bg-primary hover:text-primary-ink">
                  {playing === t.id ? <Pause size={12} fill="currentColor" /> : <Play size={12} fill="currentColor" className="ml-px" />}
                </button>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-fg">{t.title}</div>
                  <div className="text-2xs text-fg-faint">{t.mood} · {Math.round(t.tempo)} BPM</div>
                </div>
                <button aria-label={favs.includes(t.id) ? `Unfavourite ${t.title}` : `Favourite ${t.title}`} aria-pressed={favs.includes(t.id)} onClick={() => favourite(t.id)}
                  className={cx("flex h-7 w-7 items-center justify-center rounded", favs.includes(t.id) ? "text-danger" : "text-fg-faint hover:text-fg")}>
                  <Heart size={13} fill={favs.includes(t.id) ? "currentColor" : "none"} />
                </button>
                <Button size="sm" variant={active ? "secondary" : "primary"} disabled={active} onClick={() => apply(t)}>
                  {active ? "In use" : current ? "Replace" : "Apply"}
                </Button>
              </div>
              <p className="mt-1.5 text-2xs leading-4 text-fg-muted">{t.reason}</p>
            </li>
          );
        })}
      </ul>
      {data && <p className="mt-2 text-2xs text-fg-faint">{data.attribution} · {data.license}. Music ducks under speech automatically.</p>}
    </section>
  );
}

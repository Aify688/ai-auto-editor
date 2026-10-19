import type { AiSettings, AudioClip, Edl, ProjectDoc } from "../types";
import { primaryMusic, setPrimaryMusic } from "./timelineOps";

export type MusicMode = "auto" | "choose" | "none";

/** The mode shown in the Music panel. A project that never chose is treated as Auto (Auto-edit picks music for it). */
export const musicModeOf = (s: Pick<AiSettings, "musicMode">): MusicMode => s.musicMode ?? "auto";

/** The id a library track carries in the timeline: "lib:<mood>". */
export const isLibraryId = (id: string) => id.startsWith("lib:");

/** Put a chosen track on the timeline as THE music track (replacing any existing one, never adding a second) and
 *  remember the choice so Auto-edit keeps it. Without a timeline yet, only the choice is stored. */
export function withChosenTrack(d: ProjectDoc, mediaId: string, opts: { volume?: number } = {}): ProjectDoc {
  const lib = isLibraryId(mediaId);
  const prev = d.edl ? primaryMusic(d.edl) : undefined;
  const volume = opts.volume ?? prev?.volume ?? d.settings.musicVolume;
  const settings: AiSettings = {
    ...d.settings,
    musicMode: "choose",
    musicSource: lib ? "library" : "upload",
    musicMood: lib ? (mediaId.slice(4) as AiSettings["musicMood"]) : d.settings.musicMood,
    musicId: lib ? null : mediaId,
    musicVolume: Math.max(0.02, volume),
  };
  if (!d.edl) return { ...d, settings };
  // a replacement keeps the user's volume, start and fades, but starts the new song from its beginning
  const patch: Partial<AudioClip> & { mediaId: string } = { mediaId, volume, trimIn: 0, duration: null, loop: true, duck: prev?.duck ?? true };
  return { ...d, settings, edl: setPrimaryMusic(d.edl, patch) };
}

export function withoutMusic(d: ProjectDoc): ProjectDoc {
  const settings: AiSettings = { ...d.settings, musicMode: "none", musicSource: "none", musicId: null };
  return { ...d, settings, edl: d.edl ? setPrimaryMusic(d.edl, null) : d.edl };
}

export function withAutoMusic(d: ProjectDoc, autoTrackId: string | null): ProjectDoc {
  const settings: AiSettings = { ...d.settings, musicMode: "auto", musicSource: "auto", musicId: null };
  const edl: Edl | null = d.edl && autoTrackId ? setPrimaryMusic(d.edl, { mediaId: autoTrackId, volume: d.settings.musicVolume, trimIn: 0, loop: true, duck: true }) : d.edl;
  return { ...d, settings, edl };
}

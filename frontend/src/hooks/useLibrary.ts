import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MusicLibraryTrack } from "../types";

let cache: MusicLibraryTrack[] | null = null;
let pending: Promise<MusicLibraryTrack[]> | null = null;

/** The bundled music library (small and fixed), fetched once for the whole app. */
export function useLibrary(): MusicLibraryTrack[] {
  const [lib, setLib] = useState<MusicLibraryTrack[]>(cache ?? []);
  useEffect(() => {
    if (cache) return;
    let alive = true;
    pending ??= api.musicLibrary().then((l) => (cache = l)).catch(() => []);
    pending.then((l) => alive && setLib(l));
    return () => { alive = false; };
  }, []);
  return lib;
}

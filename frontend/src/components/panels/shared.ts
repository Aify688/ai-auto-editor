import { useStore } from "../../store/project";
import type { Edl } from "../../types";

/** Apply a change to the current EDL (no-op when there is none). */
export function editEdl(recipe: (e: Edl) => Edl, coalesce?: string) {
  useStore.getState().updateDoc((d) => (d.edl ? { ...d, edl: recipe(d.edl) } : d), { coalesce });
}

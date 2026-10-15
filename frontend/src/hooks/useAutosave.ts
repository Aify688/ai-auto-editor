import { useEffect } from "react";
import { api } from "../services/api";
import { useStore } from "../store/project";

const DEBOUNCE_MS = 700;

/** Persist name + document changes to the backend shortly after each edit. */
export function useAutosave() {
  useEffect(() => {
    let timer: number | undefined;
    let inFlight = false;
    let again = false;

    const save = async () => {
      const { project, doc } = useStore.getState();
      if (!project || !doc) return;
      if (inFlight) {
        again = true;
        return;
      }
      inFlight = true;
      useStore.getState().markSaved("saving");
      try {
        await api.updateProject(project.id, { name: project.name, doc });
        // Only mark saved if nothing changed while the request was in flight.
        const s = useStore.getState();
        if (s.doc === doc && s.project?.name === project.name) s.markSaved("saved");
        else again = true;
      } catch (e) {
        useStore.getState().markSaved("error", (e as Error).message);
      } finally {
        inFlight = false;
        if (again) {
          again = false;
          window.clearTimeout(timer);
          timer = window.setTimeout(save, DEBOUNCE_MS);
        }
      }
    };

    const unsub = useStore.subscribe((s, prev) => {
      if (s.saveState === "dirty" && (s.doc !== prev.doc || s.project?.name !== prev.project?.name || prev.saveState !== "dirty")) {
        window.clearTimeout(timer);
        timer = window.setTimeout(save, DEBOUNCE_MS);
      }
    });

    // Flush pending edits if the tab is closed mid-debounce.
    const flush = () => {
      const { project, doc, saveState } = useStore.getState();
      if (project && doc && saveState === "dirty") {
        fetch(`/api/projects/${project.id}`, {
          method: "PUT",
          keepalive: true,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: project.name, doc }),
        });
      }
    };
    window.addEventListener("pagehide", flush);
    return () => {
      unsub();
      window.clearTimeout(timer);
      window.removeEventListener("pagehide", flush);
    };
  }, []);
}

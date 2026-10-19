import { AlertTriangle, CheckCircle2, Info, Loader2, RotateCw, X } from "lucide-react";
import { useEffect, useState } from "react";
import { AiEditPanel } from "./components/ai-editor/AiEditPanel";
import { ExportDialog } from "./components/export/ExportDialog";
import { ProjectsDialog } from "./components/layout/ProjectsDialog";
import { SettingsDialog } from "./components/layout/SettingsDialog";
import { SideNav } from "./components/layout/SideNav";
import { TopBar } from "./components/layout/TopBar";
import { MediaPanel } from "./components/media/MediaPanel";
import { AudioPanel } from "./components/panels/AudioPanel";
import { CaptionsPanel } from "./components/panels/CaptionsPanel";
import { EffectsPanel } from "./components/panels/EffectsPanel";
import { InsightsPanel } from "./components/panels/InsightsPanel";
import { TemplatesPanel } from "./components/panels/TemplatesPanel";
import { TextPanel } from "./components/panels/TextPanel";
import { PreviewPanel } from "./components/preview/PreviewPanel";
import { Timeline, timelineActions } from "./components/timeline/Timeline";
import { Button, cx } from "./components/ui/controls";
import { useAutosave } from "./hooks/useAutosave";
import { useJobPoller, useMediaPoller } from "./hooks/useJobs";
import { api } from "./services/api";
import { lastProjectId, useStore } from "./store/project";
import type { NavKey } from "./types";

const PANELS: Record<NavKey, () => JSX.Element> = {
  media: MediaPanel,
  ai: InsightsPanel,
  audio: AudioPanel,
  text: TextPanel,
  captions: CaptionsPanel,
  effects: EffectsPanel,
  templates: TemplatesPanel,
};

function Toasts() {
  const toasts = useStore((s) => s.toasts);
  const dismiss = useStore((s) => s.dismissToast);
  return (
    <div className="pointer-events-none fixed bottom-4 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2" aria-live="polite">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cx(
            "pointer-events-auto flex max-w-[520px] items-start gap-2 rounded-md border bg-panel px-3 py-2 text-sm shadow-xl animate-[slideup_160ms_ease-out]",
            t.kind === "error" ? "border-danger/50" : t.kind === "success" ? "border-success/40" : "border-line",
          )}
        >
          {t.kind === "error" ? <AlertTriangle size={15} className="mt-0.5 shrink-0 text-danger" /> : t.kind === "success" ? <CheckCircle2 size={15} className="mt-0.5 shrink-0 text-success" /> : <Info size={15} className="mt-0.5 shrink-0 text-primary" />}
          <span className="text-fg">{t.text}</span>
          <button aria-label="Dismiss" onClick={() => dismiss(t.id)} className="ml-1 text-fg-muted hover:text-fg"><X size={14} /></button>
        </div>
      ))}
    </div>
  );
}

function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el.closest("input, textarea, select, [contenteditable=true]") || document.querySelector("[role=dialog]")) return;
      const s = useStore.getState();
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) s.redo();
        else s.undo();
      } else if (mod && e.key.toLowerCase() === "y") {
        e.preventDefault();
        s.redo();
      } else if (e.key === " ") {
        e.preventDefault();
        s.setPlaying(!s.playing);
      } else if ((e.key === "Delete" || e.key === "Backspace") && (s.selectedClipId || s.selectedAudioId || s.selectedTextId || s.selectedCaptionId)) {
        e.preventDefault();
        timelineActions.remove?.();
      } else if (mod && e.key.toLowerCase() === "d") {
        e.preventDefault();
        timelineActions.duplicate?.();
      } else if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
        e.preventDefault();
        timelineActions.nudge?.(e.key === "ArrowLeft" ? -1 : 1, e.shiftKey);
      } else if (e.key === "Escape") {
        s.selectClip(null);
        s.selectAudio(null);
        s.selectText(null);
        s.selectCaption(null);
      } else if (e.key.toLowerCase() === "m" && !mod) {
        timelineActions.marker?.();
      } else if (e.key.toLowerCase() === "s" && !mod) {
        timelineActions.split?.();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

function Boot({ children }: { children: React.ReactNode }) {
  const project = useStore((s) => s.project);
  const [error, setError] = useState<string | null>(null);

  const boot = async () => {
    setError(null);
    try {
      const s = useStore.getState();
      s.setSystem(await api.system());
      const last = lastProjectId.get();
      const list = await api.listProjects();
      const target = list.find((p) => p.id === last) ?? list[0];
      if (target) await s.openProject(target.id);
      else await s.newProject("My first video");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  useEffect(() => {
    boot();
  }, []);

  if (error)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-app text-center">
        <AlertTriangle className="text-danger" />
        <div className="text-sm text-fg">FrameFlow could not start</div>
        <div className="max-w-md text-xs text-fg-muted">{error}</div>
        <Button icon={<RotateCw size={14} />} onClick={boot}>Try again</Button>
      </div>
    );
  if (!project)
    return (
      <div className="flex h-full items-center justify-center bg-app">
        <Loader2 className="animate-spin text-fg-muted" />
      </div>
    );
  return <>{children}</>;
}

function Workspace() {
  const nav = useStore((s) => s.nav);
  const ffmpegMissing = useStore((s) => s.system && !s.system.ffmpeg.ok);
  const stale = useStore((s) => !!s.system?.server?.stale);
  const Panel = PANELS[nav];
  useAutosave();
  useJobPoller();
  useMediaPoller();
  useShortcuts();
  return (
    <div className="flex h-full min-w-[1180px] flex-col bg-app text-fg">
      <TopBar />
      {stale && (
        <div role="alert" className="flex items-center gap-2 border-b border-warn/40 bg-warn/10 px-4 py-1.5 text-xs text-warn">
          <AlertTriangle size={13} /> This server was started before the app was updated, so some features may fail. Restart it with ./start.sh --restart and reload.
        </div>
      )}
      {ffmpegMissing && (
        <div className="flex items-center gap-2 border-b border-danger/40 bg-danger/10 px-4 py-1.5 text-xs text-danger">
          <AlertTriangle size={13} /> FFmpeg was not found. Install it (macOS: brew install ffmpeg) and restart the backend.
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <SideNav />
        <div className="w-[300px] shrink-0 border-r border-line bg-panel">
          <Panel />
        </div>
        <PreviewPanel />
        <AiEditPanel />
      </div>
      <Timeline />
      <ProjectsDialog />
      <SettingsDialog />
      <ExportDialog />
    </div>
  );
}

export default function App() {
  return (
    <>
      <Boot>
        <Workspace />
      </Boot>
      <Toasts />
    </>
  );
}

import { AlertCircle, Check, FolderOpen, Loader2, Redo2, Undo2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStore } from "../../store/project";
import { Button, IconButton } from "../ui/controls";
import { WorkflowSteps } from "./WorkflowSteps";

export function Logo() {
  return (
    <div className="flex items-center gap-2">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#508CFF" />
        <path d="M10 9h12v3.2h-8.6v3.1h7.4v3.1h-7.4V23H10z" fill="#fff" />
      </svg>
      <span className="text-[14px] font-semibold tracking-tight">FrameFlow</span>
    </div>
  );
}

function ProjectName() {
  const name = useStore((s) => s.project?.name ?? "");
  const rename = useStore((s) => s.rename);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => setDraft(name), [name]);
  useEffect(() => {
    if (editing) ref.current?.select();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft.trim()) rename(draft.trim());
    else setDraft(name);
  };

  if (editing)
    return (
      <input
        ref={ref}
        value={draft}
        maxLength={120}
        aria-label="Project name"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") {
            setDraft(name);
            setEditing(false);
          }
        }}
        className="h-7 w-56 rounded border border-primary bg-panel2 px-2 text-sm text-fg outline-none"
      />
    );
  return (
    <button
      onClick={() => setEditing(true)}
      title="Rename project"
      className="h-7 max-w-[260px] truncate rounded px-2 text-sm font-medium text-fg transition-colors hover:bg-panel2"
    >
      {name}
    </button>
  );
}

function SaveStatus() {
  const state = useStore((s) => s.saveState);
  const error = useStore((s) => s.saveError);
  if (state === "saving" || state === "dirty")
    return (
      <span className="flex items-center gap-1 text-xs text-fg-muted">
        <Loader2 size={12} className="animate-spin" /> Saving…
      </span>
    );
  if (state === "error")
    return (
      <span className="flex items-center gap-1 text-xs text-danger" title={error ?? ""}>
        <AlertCircle size={12} /> Not saved
      </span>
    );
  if (state === "saved")
    return (
      <span className="flex items-center gap-1 text-xs text-fg-muted">
        <Check size={12} className="text-success" /> Saved
      </span>
    );
  return null;
}

export function TopBar() {
  const canUndo = useStore((s) => s.past.length > 0);
  const canRedo = useStore((s) => s.future.length > 0);
  const undo = useStore((s) => s.undo);
  const redo = useStore((s) => s.redo);
  const openProjects = useStore((s) => s.setProjectsOpen);
  const openExport = useStore((s) => s.setExportOpen);
  const hasEdl = useStore((s) => !!s.doc?.edl?.clips.length);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-panel px-3">
      <div className="flex min-w-0 flex-1 basis-0 items-center gap-3">
        <Logo />
        <div className="h-5 w-px bg-line" />
        <IconButton label="Projects" onClick={() => openProjects(true)}>
          <FolderOpen size={16} />
        </IconButton>
        <ProjectName />
        <SaveStatus />
      </div>
      <WorkflowSteps />
      <div className="flex flex-1 basis-0 items-center justify-end gap-1">
        <IconButton label="Undo (⌘Z)" onClick={undo} disabled={!canUndo}>
          <Undo2 size={16} />
        </IconButton>
        <IconButton label="Redo (⇧⌘Z)" onClick={redo} disabled={!canRedo}>
          <Redo2 size={16} />
        </IconButton>
        <div className="mx-2 h-5 w-px bg-line" />
        <Button
          variant="primary"
          icon={<Upload size={14} />}
          onClick={() => openExport(true)}
          disabled={!hasEdl}
          title={hasEdl ? "Export video" : "Generate an AI edit first"}
        >
          Export
        </Button>
      </div>
    </header>
  );
}

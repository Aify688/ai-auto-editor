import { Film, FolderOpen, Loader2, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { fmtAgo, fmtDuration } from "../../lib/format";
import { api } from "../../services/api";
import { lastProjectId, useStore } from "../../store/project";
import type { ProjectSummary } from "../../types";
import { Button, Modal, cx } from "../ui/controls";

export function ProjectsDialog() {
  const open = useStore((s) => s.projectsOpen);
  const setOpen = useStore((s) => s.setProjectsOpen);
  const currentId = useStore((s) => s.project?.id);
  const [list, setList] = useState<ProjectSummary[] | null>(null);
  const [name, setName] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.listProjects().then(setList).catch((e) => useStore.getState().toast(e.message, "error"));
  useEffect(() => {
    if (open) {
      setList(null);
      setConfirmId(null);
      refresh();
    }
  }, [open]);

  const openProject = async (id: string) => {
    setBusy(true);
    try {
      await useStore.getState().openProject(id);
      setOpen(false);
    } catch (e) {
      useStore.getState().toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    try {
      await useStore.getState().newProject(name.trim() || "Untitled project");
      setName("");
      setOpen(false);
    } catch (e) {
      useStore.getState().toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    try {
      await api.deleteProject(id);
      setConfirmId(null);
      if (id === currentId) {
        lastProjectId.set(null);
        const rest = (list ?? []).filter((p) => p.id !== id);
        if (rest.length) await useStore.getState().openProject(rest[0].id);
        else await useStore.getState().newProject();
      }
      refresh();
    } catch (e) {
      useStore.getState().toast((e as Error).message, "error");
    }
  };

  return (
    <Modal open={open} onClose={() => setOpen(false)} title="Projects" width={560}>
      <div className="flex gap-2 border-b border-line px-4 py-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()}
          placeholder="New project name"
          aria-label="New project name"
          maxLength={120}
          className="h-8 flex-1 rounded border border-line bg-panel2 px-2 text-sm text-fg outline-none placeholder:text-fg-faint focus:border-primary"
        />
        <Button variant="primary" icon={<Plus size={14} />} onClick={create} disabled={busy}>Create</Button>
      </div>
      <div className="max-h-[420px] overflow-y-auto p-2">
        {list === null ? (
          <div className="flex justify-center py-8"><Loader2 className="animate-spin text-fg-muted" size={18} /></div>
        ) : list.length === 0 ? (
          <div className="py-8 text-center text-xs text-fg-muted">No saved projects.</div>
        ) : (
          list.map((p) => (
            <div key={p.id} className={cx("group flex items-center gap-3 rounded-md px-2 py-2", p.id === currentId ? "bg-primary-muted" : "hover:bg-panel2")}>
              <div className="flex h-10 w-16 shrink-0 items-center justify-center overflow-hidden rounded bg-panel2">
                {p.coverUrl ? <img src={p.coverUrl} alt="" className="h-full w-full object-cover" /> : <Film size={16} className="text-fg-faint" />}
              </div>
              <button className="min-w-0 flex-1 text-left" onClick={() => openProject(p.id)} disabled={busy}>
                <div className="truncate text-sm text-fg">{p.name}{p.id === currentId && <span className="ml-2 text-2xs text-primary">Open</span>}</div>
                <div className="text-2xs text-fg-faint">
                  {p.mediaCount} file{p.mediaCount === 1 ? "" : "s"} · {p.hasRender ? `edit ${fmtDuration(p.renderDuration)}` : "not generated"} · {fmtAgo(p.updatedAt)}
                </div>
              </button>
              {confirmId === p.id ? (
                <div className="flex items-center gap-1">
                  <span className="text-2xs text-danger">Delete project and files?</span>
                  <Button size="sm" variant="danger" onClick={() => remove(p.id)}>Delete</Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)}>Cancel</Button>
                </div>
              ) : (
                <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <Button size="sm" variant="ghost" icon={<FolderOpen size={13} />} onClick={() => openProject(p.id)}>Open</Button>
                  <button aria-label="Delete project" onClick={() => setConfirmId(p.id)} className="flex h-7 w-7 items-center justify-center rounded text-fg-muted hover:bg-panel2 hover:text-danger">
                    <Trash2 size={14} />
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}

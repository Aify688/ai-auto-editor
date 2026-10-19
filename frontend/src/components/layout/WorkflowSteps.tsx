import { Check } from "lucide-react";
import { isActive, startJob } from "../../hooks/useJobs";
import { generationState } from "../../lib/generation";
import { useStore } from "../../store/project";
import { cx } from "../ui/controls";

const LABELS = ["Upload", "Style", "Generate", "Review", "Export"] as const;

/** Five-step guide derived from existing store state; it adds no state of its own. */
export function WorkflowSteps() {
  const media = useStore((s) => s.media);
  const job = useStore((s) => s.jobs.generate);
  const hasEdit = useStore((s) => !!s.doc?.edl?.clips.length);
  const exporting = useStore((s) => s.exportOpen);
  const setNav = useStore((s) => s.setNav);
  const setPreviewMode = useStore((s) => s.setPreviewMode);
  const setExportOpen = useStore((s) => s.setExportOpen);

  const instruction = useStore((s) => s.doc?.settings.instruction ?? "");
  const hasMedia = media.some((m) => m.kind !== "audio" && m.status === "ready");
  const generating = isActive(job);
  const current = exporting ? 4 : generating ? 2 : hasEdit ? 3 : hasMedia ? 1 : 0;

  const go = [
    () => setNav("media"),
    () => {
      const group = document.querySelector<HTMLElement>('[aria-label="Editing style"]');
      group?.scrollIntoView({ block: "nearest" });
      group?.querySelector<HTMLElement>("[aria-checked=true]")?.focus();
    },
    () => {
      if (canGenerate) startJob("generate");
    },
    () => {
      if (hasEdit) setPreviewMode("edit");
    },
    () => {
      if (hasEdit) setExportOpen(true);
    },
  ];
  const canGenerate = generationState({ visualCount: media.filter((m) => m.kind !== "audio").length, readyCount: media.filter((m) => m.kind !== "audio" && m.status === "ready").length,
    processing: media.some((m) => m.status === "processing"), instruction, running: generating, hasEdit }).enabled;
  const enabled = [true, hasMedia, canGenerate, hasEdit, hasEdit];

  return (
    <nav aria-label="Workflow" className="flex items-center">
      {LABELS.map((label, i) => {
        const done = i < current;
        const on = i === current;
        return (
          <div key={label} className="flex items-center">
            {i > 0 && <span className="mx-1 h-px w-4 bg-line" aria-hidden />}
            <button
              onClick={go[i]}
              disabled={!enabled[i]}
              aria-current={on ? "step" : undefined}
              title={label}
              className={cx(
                "flex h-8 items-center gap-2 rounded-full px-2.5 text-sm font-medium transition-colors duration-150",
                "disabled:cursor-default disabled:opacity-45 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/60",
                on ? "bg-raise text-fg" : done ? "text-fg-muted hover:text-fg" : "text-fg-faint hover:text-fg",
              )}
            >
              <span
                className={cx(
                  "flex h-5 w-5 items-center justify-center rounded-full text-2xs",
                  on ? "bg-primary text-primary-ink" : done ? "bg-success/20 text-success" : "border border-line",
                )}
              >
                {done ? <Check size={12} strokeWidth={2.5} /> : i + 1}
              </span>
              <span className="hidden xl:inline">{label}</span>
            </button>
          </div>
        );
      })}
    </nav>
  );
}

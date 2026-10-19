import { Check, LayoutTemplate } from "lucide-react";
import { useEffect, useState } from "react";
import { STYLES } from "../../lib/styles";
import { api } from "../../services/api";
import { useStore } from "../../store/project";
import type { TemplateDef } from "../../types";
import { Button, PanelHeader, cx } from "../ui/controls";

/**
 * Templates are optional STRUCTURE: sections, text placeholders, a suggested length and format.
 * They are separate from editing styles (pacing, transitions, colour, music mood), which are chosen in AI Edit.
 */
export function TemplatesPanel() {
  const template = useStore((s) => s.doc?.template ?? null);
  const style = useStore((s) => s.doc!.style);
  const updateDoc = useStore((s) => s.updateDoc);
  const toast = useStore((s) => s.toast);
  const [list, setList] = useState<TemplateDef[]>([]);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.templates().then(setList).catch(() => setError(true));
  }, []);

  const use = (t: TemplateDef) => {
    updateDoc((d) => ({
      ...d,
      template: t.id,
      aspect: t.aspect,
      settings: { ...d.settings, targetDuration: d.settings.targetDuration ?? t.duration, musicMood: d.settings.musicMood ?? t.mood },
      edl: d.edl ? { ...d.edl, aspect: t.aspect } : d.edl,
    }));
    toast(`"${t.name}" selected. Click Generate AI Video to lay out your clips.`, "success");
  };
  const clear = () => updateDoc((d) => ({ ...d, template: null }));

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Templates" subtitle="Optional layouts. Your editing style stays separate." />
      <div className="flex-1 space-y-2 overflow-y-auto px-4 pb-4">
        <button
          onClick={clear}
          aria-pressed={!template}
          className={cx("flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left", !template ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]")}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-app text-fg-muted"><LayoutTemplate size={17} /></div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-fg">No template</div>
            <div className="text-2xs text-fg-muted">Let the AI arrange everything · {STYLES[style].name} style</div>
          </div>
          {!template && <Check size={14} className="text-primary" />}
        </button>
        {error && <p className="text-2xs text-danger">Templates could not be loaded.</p>}
        {list.map((t) => {
          const active = template === t.id;
          return (
            <div key={t.id} className={cx("rounded-xl border p-3", active ? "border-primary bg-primary-muted" : "border-line bg-panel2")}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-fg">{t.name}</div>
                  <div className="text-2xs text-fg-muted">{t.description}</div>
                </div>
                <Button size="sm" variant={active ? "secondary" : "primary"} disabled={active} onClick={() => use(t)}>{active ? "Selected" : "Use"}</Button>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {t.sections.map((s) => <span key={s.name} className="rounded-full bg-app px-2 py-0.5 text-2xs text-fg-muted">{s.name}</span>)}
              </div>
              <div className="mt-1.5 text-2xs text-fg-faint">{t.duration}s · {t.aspect} · works with any style (suggested: {STYLES[t.suggestedStyle].name})</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

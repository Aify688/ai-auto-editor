import { RectangleHorizontal, RectangleVertical, Square } from "lucide-react";
import { STYLES } from "../../lib/styles";
import { useStore } from "../../store/project";
import type { AiSettings, Aspect, Style } from "../../types";
import { PanelHeader } from "../ui/controls";

interface Template {
  name: string;
  use: string;
  style: Style;
  aspect: Aspect;
  settings: Partial<AiSettings>;
}

const TEMPLATES: Template[] = [
  { name: "Reels highlight", use: "TikTok · Reels · Shorts", style: "dynamic", aspect: "9:16", settings: { targetDuration: 20, captions: false, beatSync: true, removeSilence: false, smartCrop: true } },
  { name: "Talking-head short", use: "Captioned vertical clip", style: "vlog", aspect: "9:16", settings: { targetDuration: 45, captions: true, burnCaptions: true, removeSilence: true, smartCrop: true } },
  { name: "YouTube vlog", use: "Everyday story", style: "vlog", aspect: "16:9", settings: { targetDuration: null, captions: true, removeSilence: true } },
  { name: "Travel film", use: "Slow, graded montage", style: "cinematic", aspect: "16:9", settings: { targetDuration: 45, captions: false, removeSilence: false } },
  { name: "Square promo", use: "Feed post · 15 s", style: "dynamic", aspect: "1:1", settings: { targetDuration: 15, captions: false, removeSilence: false } },
  { name: "Vertical trailer", use: "Cinematic 9:16 teaser", style: "cinematic", aspect: "9:16", settings: { targetDuration: 30, captions: false, removeSilence: false, smartCrop: true } },
];

const ICON = { "16:9": RectangleHorizontal, "9:16": RectangleVertical, "1:1": Square };

export function TemplatesPanel() {
  const updateDoc = useStore((s) => s.updateDoc);
  const current = useStore((s) => s.doc!);

  const apply = (t: Template) => {
    updateDoc((d) => ({
      ...d,
      style: t.style,
      aspect: t.aspect,
      settings: { ...d.settings, ...STYLES[t.style].defaults, ...t.settings },
      edl: d.edl && { ...d.edl, aspect: t.aspect },
    }));
    useStore.getState().toast(`"${t.name}" applied. Click Generate AI Video.`, "success");
  };

  return (
    <div className="flex h-full flex-col">
      <PanelHeader title="Templates" subtitle="One-click setups for common formats." />
      <div className="flex-1 space-y-1.5 overflow-y-auto px-4 pb-4">
        {TEMPLATES.map((t) => {
          const Icon = ICON[t.aspect];
          const active = current.style === t.style && current.aspect === t.aspect && current.settings.targetDuration === (t.settings.targetDuration ?? null);
          return (
            <button
              key={t.name}
              onClick={() => apply(t)}
              className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors ${active ? "border-primary bg-primary-muted" : "border-line bg-panel2 hover:border-[#4A5160]"}`}
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-app text-fg-muted"><Icon size={17} /></div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-fg">{t.name}</div>
                <div className="truncate text-2xs text-fg-muted">
                  {t.use} · {STYLES[t.style].name} · {t.aspect}{t.settings.targetDuration ? ` · ${t.settings.targetDuration}s` : ""}
                </div>
              </div>
            </button>
          );
        })}
        <p className="pt-1 text-2xs text-fg-faint">Templates set style, format and AI settings; nothing is rendered until you generate.</p>
      </div>
    </div>
  );
}

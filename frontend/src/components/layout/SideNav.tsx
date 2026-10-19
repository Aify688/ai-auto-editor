import { AudioLines, Captions, Clapperboard, ImagePlay, LayoutTemplate, Sparkles, Type, Wand2 } from "lucide-react";
import { useStore } from "../../store/project";
import type { NavKey } from "../../types";
import { cx } from "../ui/controls";

export const NAV_ITEMS: { key: NavKey; label: string; icon: typeof Clapperboard }[] = [
  { key: "media", label: "Media", icon: Clapperboard },
  { key: "ai", label: "AI Edit", icon: Sparkles },
  { key: "audio", label: "Audio", icon: AudioLines },
  { key: "text", label: "Text", icon: Type },
  { key: "captions", label: "Captions", icon: Captions },
  { key: "effects", label: "Effects", icon: Wand2 },
  { key: "animate", label: "Animate", icon: ImagePlay },
  { key: "templates", label: "Templates", icon: LayoutTemplate },
];

export function SideNav() {
  const nav = useStore((s) => s.nav);
  const setNav = useStore((s) => s.setNav);
  return (
    <nav aria-label="Panels" className="flex w-[64px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel py-2">
      {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
        <button
          key={key}
          onClick={() => setNav(key)}
          aria-current={nav === key ? "page" : undefined}
          className={cx(
            "flex w-[54px] flex-col items-center gap-1 rounded-md py-2 text-2xs transition-colors duration-150",
            nav === key ? "bg-primary-muted text-primary" : "text-fg-muted hover:bg-panel2 hover:text-fg",
          )}
        >
          <Icon size={18} strokeWidth={1.75} />
          {label}
        </button>
      ))}
    </nav>
  );
}

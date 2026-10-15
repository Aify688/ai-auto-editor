import { ChevronDown, X } from "lucide-react";
import { useEffect, type ButtonHTMLAttributes, type ReactNode } from "react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

type BtnVariant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md" | "lg"; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded font-medium transition-colors duration-150",
        "disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/60",
        size === "sm" && "h-7 px-2.5 text-xs",
        size === "md" && "h-8 px-3 text-sm",
        size === "lg" && "h-10 px-4 text-base",
        variant === "primary" && "bg-primary text-white hover:bg-primary-hover",
        variant === "secondary" && "border border-line bg-panel2 text-fg hover:border-[#4A5160] hover:bg-[#2D323C]",
        variant === "ghost" && "text-fg-muted hover:bg-panel2 hover:text-fg",
        variant === "danger" && "bg-danger/90 text-white hover:bg-danger",
        className,
      )}
    >
      {icon}
      {children}
    </button>
  );
}

export function IconButton({
  label,
  active,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; active?: boolean }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex h-7 w-7 items-center justify-center rounded text-fg-muted transition-colors duration-150",
        "hover:bg-panel2 hover:text-fg disabled:pointer-events-none disabled:opacity-35",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary/60",
        active && "bg-primary-muted text-primary",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative h-[18px] w-8 shrink-0 rounded-full transition-colors duration-150 disabled:opacity-40",
        checked ? "bg-primary" : "bg-line",
      )}
    >
      <span
        className={cx(
          "absolute left-0 top-[2px] h-[14px] w-[14px] rounded-full bg-white shadow transition-transform duration-150",
          checked ? "translate-x-[16px]" : "translate-x-[2px]",
        )}
      />
    </button>
  );
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  disabled,
  label,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (v: number) => void;
  disabled?: boolean;
  label: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <input
      type="range"
      aria-label={label}
      min={min}
      max={max}
      step={step}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(Number(e.target.value))}
      className="ff-range w-full"
      style={{ background: `linear-gradient(to right, #508CFF ${pct}%, #383E49 ${pct}%)` }}
    />
  );
}

export function Select<T extends string | number>({
  value,
  options,
  onChange,
  label,
  disabled,
  className,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div className={cx("relative", className)}>
      <select
        aria-label={label}
        value={String(value)}
        disabled={disabled}
        onChange={(e) => {
          const hit = options.find((o) => String(o.value) === e.target.value);
          if (hit) onChange(hit.value);
        }}
        className="h-7 w-full appearance-none rounded border border-line bg-panel2 pl-2 pr-7 text-xs text-fg outline-none transition-colors hover:border-[#4A5160] focus:border-primary disabled:opacity-45"
      >
        {options.map((o) => (
          <option key={String(o.value)} value={String(o.value)}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={13} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-fg-muted" />
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded border border-line bg-panel2 p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          title={o.title}
          onClick={() => onChange(o.value)}
          className={cx(
            "flex-1 rounded-[4px] px-2 py-1 text-xs transition-colors",
            o.value === value ? "bg-primary text-white" : "text-fg-muted hover:text-fg",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = 480,
  dismissable = true,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: number;
  dismissable?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && dismissable && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, dismissable]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 animate-[fadein_120ms_ease-out]"
      onMouseDown={(e) => e.target === e.currentTarget && dismissable && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        style={{ width }}
        className="max-h-[90vh] max-w-full overflow-auto rounded-lg border border-line bg-panel shadow-2xl"
      >
        <div className="flex h-11 items-center justify-between border-b border-line px-4">
          <h2 className="text-base font-semibold">{title}</h2>
          {dismissable && (
            <IconButton label="Close" onClick={onClose}>
              <X size={16} />
            </IconButton>
          )}
        </div>
        {children}
      </div>
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <div className="text-xs text-fg">{label}</div>
        {hint && <div className="text-2xs text-fg-faint">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

export function PanelHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-2 px-4 pb-3 pt-4">
      <div>
        <h2 className="text-[14px] font-semibold leading-5 text-fg">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-fg-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Empty({ icon, title, text, action }: { icon: ReactNode; title: string; text?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-10 text-center">
      <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-panel2 text-fg-muted">{icon}</div>
      <div className="text-sm font-medium text-fg">{title}</div>
      {text && <div className="mt-1 max-w-[240px] text-xs text-fg-muted">{text}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

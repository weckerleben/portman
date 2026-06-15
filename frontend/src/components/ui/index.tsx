import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "solid" | "ghost" | "danger" | "accent";

const VARIANTS: Record<Variant, string> = {
  solid: "bg-ink-600 hover:bg-ink-500 text-haze-200 border-white/10",
  ghost: "bg-transparent hover:bg-white/5 text-haze-300 border-white/10",
  danger: "bg-signal-rogue/10 hover:bg-signal-rogue/20 text-signal-rogue border-signal-rogue/30",
  accent: "bg-accent/15 hover:bg-accent/25 text-accent border-accent/30",
};

export function Button({
  variant = "solid",
  className = "",
  children,
  ...rest
}: { variant?: Variant } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium
        transition-colors duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60
        disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

const STATUS_TONE: Record<string, string> = {
  managed: "bg-signal-managed/12 text-signal-managed border-signal-managed/30",
  unauthorized: "bg-signal-rogue/12 text-signal-rogue border-signal-rogue/30",
  reserved: "bg-signal-reserved/12 text-signal-reserved border-signal-reserved/30",
  idle: "bg-signal-idle/12 text-signal-idle border-signal-idle/30",
};

export function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? STATUS_TONE.idle;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${tone}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

export function Panel({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel-surface flex flex-col overflow-hidden ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <h2 className="text-sm font-semibold tracking-wide text-haze-200">{title}</h2>
          {action}
        </header>
      )}
      <div className="flex-1 overflow-auto">{children}</div>
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="flex flex-col">
      <span className={`tnum text-2xl font-semibold ${tone}`}>{value}</span>
      <span className="text-[11px] uppercase tracking-wider text-haze-400">{label}</span>
    </div>
  );
}

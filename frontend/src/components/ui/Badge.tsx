import type { ReactNode } from "react";

/** Solo estados semánticos reales (CLAUDE.md §5: nada de badges decorativos). */
type Tone = "neutral" | "ok" | "warn" | "danger" | "accent";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "bg-line/60 text-ink-2",
  ok: "bg-ok/10 text-ok",
  warn: "bg-warn/10 text-warn",
  danger: "bg-danger/10 text-danger",
  accent: "bg-accent/10 text-accent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}

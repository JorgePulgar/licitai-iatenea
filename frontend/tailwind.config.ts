import type { Config } from "tailwindcss";

/**
 * Sistema de diseño Pliexa (spec-fe-design A1).
 * Los valores viven como CSS variables en src/styles/tokens.css; Tailwind solo
 * los consume — ningún color crudo en páginas/componentes.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--color-bg) / <alpha-value>)",
        surface: "rgb(var(--color-surface) / <alpha-value>)",
        "ink-1": "rgb(var(--color-ink-1) / <alpha-value>)",
        "ink-2": "rgb(var(--color-ink-2) / <alpha-value>)",
        "ink-3": "rgb(var(--color-ink-3) / <alpha-value>)",
        line: "rgb(var(--color-line) / <alpha-value>)",
        accent: "rgb(var(--color-accent) / <alpha-value>)",
        "accent-strong": "rgb(var(--color-accent-strong) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        warn: "rgb(var(--color-warn) / <alpha-value>)",
        ok: "rgb(var(--color-ok) / <alpha-value>)",
      },
      borderRadius: {
        DEFAULT: "3px",
        md: "4px",
      },
      fontFamily: {
        sans: ["Inter Variable", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;

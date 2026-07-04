# Spec FE — Design system (FE.1) + document editor (FE.3)

> Fable-written spec, 2026-07-02. Implementers: FE.1 skeleton per this spec (Opus 4.8 acceptable since spec exists), FE.2/FE.3 Opus. Review checklist at end.
> Constraint reminder: full rewrite — never port old `frontend/src` files. Old app may be RUN to observe behavior; behavior notes go into per-page checklists, code does not.

## Part A — Design system & skeleton (FE.1)

### A1. Foundations

- Stack: Vite + React 18 + TypeScript strict + Tailwind. **pnpm only** — delete `bun.lock`, `package-lock.json` at the start (needs Jorge's file-deletion OK, flagged here once).
- Design tokens as CSS variables consumed by Tailwind config (`--color-bg`, `--color-surface`, `--color-ink-1/2/3`, `--color-line`, `--color-accent`, `--color-danger/warn/ok`), light theme only v1.
- Identity (rebrand): neutral gray scale + ONE accent (recommend a desaturated indigo/steel blue ≠ old `#2563EB`), radius 2–4px, no shadows heavier than `shadow-sm`, Inter + JetBrains Mono (self-hosted via fontsource, not Google CDN — GDPR nicety). All claude.md §5 rules apply (density, no AI-look, responsive).

### A2. `components/ui/` (the base library — everything uses these)

Button (primary/secondary/ghost/danger, sm/md, loading state) · Input/Textarea/Select (label, error, help) · Card · Badge (semantic states only) · Modal (focus-trapped) · Table (dense, sortable header slot, sticky header) · Skeleton · Toast (single provider) · Tabs · EmptyState · Tooltip. Each: typed props, one test, usage doc (MD file or Storybook — MD is enough).

### A3. App skeleton

- Router: `/login`, `/licitaciones`, `/licitaciones/:id/:tab`, `/cola`, `/ajustes/:section`, `/auditoria` (admin).
- `AppShell`: collapsible sidebar (nav + org name), topbar (user menu), content area; responsive: sidebar → drawer under `md`.
- Auth: context + `ProtectedRoute` + `RequireAdmin`; token handling isolated in `lib/authToken.ts` (single swap point for httpOnly-cookie migration).
- API layer: `lib/http.ts` (fetch wrapper: base URL, auth header, error normalization → typed `ApiError`, 401 → logout redirect) + `services/<domain>.ts` per router (auth, licitaciones, uploads, query, memoria, perfil, templates, audit). No 449-line monolith.
- Server state: TanStack Query (caching, retries, invalidation — replaces ad-hoc useEffect fetching). **New dependency — flagged for Jorge's approval.**
- Testing: vitest + RTL + msw for API mocks. CI runs typecheck + tests + build (hooks into 2.3).

## Part B — Document editor (FE.3 decision)

### B1. Requirements (from product behavior, not old code)

1. Rich editing of the Memoria (headings, bold/italic, lists, tables, images later) stored as **Markdown** (backend contract: `MemoriaDocument.markdown`).
2. **Page-accurate preview**: on-screen page boundaries must match the exported PDF (A4, fixed margins), including "Página N" indicators; captions must not orphan from tables (mirror of export CSS rules).
3. Manual page-break insertion.
4. AI chat edits arrive as full/partial Markdown replacements → editor re-renders without losing cursor context catastrophically.
5. Variables/placeholders (`{{company_name}}`-style spans) survive round-trips.

### B2. Decision: **TipTap (ProseMirror) + deterministic page-guide overlay**

- TipTap StarterKit + Table + custom nodes: `pageBreak`, `documentVariable`. Markdown in/out via `tiptap-markdown` (or prosemirror-markdown serializer) — round-trip tested with tables.
- Pagination = **overlay, not reflow** (the old app's hard-won lesson: spacers that add height break CSS margin-collapsing and drift ~10px/page; push blocks with `margin-top` on the block itself and render page badges in zero-height anchors). Implement as a ProseMirror decoration plugin that measures block positions and assigns margin-top nudges + badge widgets against a fixed A4 grid. These constraints are REQUIREMENTS from bug history — reimplement the technique from this description, do not port the old plugin.
- Export fidelity: PDF preview modal uses paged.js with the same page CSS as backend WeasyPrint (5.6 keeps a single shared CSS source of truth: one file, served to both).
- Why not "custom contentEditable" (old approach): 1,359-line unmaintainable monolith, no schema, fragile selection handling. Why not CKEditor/Lexical: TipTap has the best Markdown story + headless styling fits Tailwind.

### B3. Editor module layout (target ≤200 lines/file)

`editor/Editor.tsx` (mount, toolbar) · `editor/extensions/` (pageBreak, variable, markdown config) · `editor/pagination/` (grid math, decoration plugin, badge widget) · `editor/toolbar/` · `editor/export/` (paged.js preview).

## Acceptance (FE.1 scope)

1. `pnpm install && pnpm dev` runs the shell with login + empty pages; single lockfile.
2. Every ui/ component has a test + doc entry; grep shows zero inline `bg-[#`-style raw colors outside tokens.
3. Old `frontend/src` deleted; `rg -i "integra"` in frontend → 0.
4. Lighthouse-level sanity: shell usable at 375px width.

## Opus review checklist

- [ ] Tokens in one place; components consume tokens (no hardcoded hex in pages).
- [ ] No `any` (tsconfig strict, eslint rule); no default-exported god components.
- [ ] `lib/authToken.ts` is the only module touching storage.
- [ ] TanStack Query for ALL server state (no useEffect+fetch patterns).
- [ ] Editor: pagination uses margin-top nudges + zero-height badge widgets (NO height-adding spacers — assert in test measuring cumulative drift = 0 across 20 pages).
- [ ] Markdown round-trip test: md → editor → md is stable for headings/lists/tables/pageBreak/variables.
- [ ] Shared page CSS single-sourced for paged.js preview and WeasyPrint (path referenced by both, no divergent copies).
- [ ] msw-based tests per page (FE.2+); files ≤ ~300 lines.

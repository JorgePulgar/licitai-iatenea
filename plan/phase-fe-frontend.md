# Phase FE — Frontend rebuild (full rewrite + rebrand)

> Prereq reading: `plan/00-CONTEXT.md` §2 (rewrite rules) and `claude.md` §5 (UI style rules — sober, Linear/Notion-like, responsive, no AI-look).
> The entire current `frontend/src/` is co-authored (~96% Siro) → **complete rewrite from functional specs, never porting files**. Old code may be *run* to observe behavior for spec-writing, but not copied.

## Known defects of the old SPA (avoid repeating; improve on)

- Zero tests.
- `components/ui/` has only 5 components — no Button/Input/Card; controls restyled inline everywhere.
- `RichDocumentEditor.tsx` 1,359 lines; `MemoriaTab.tsx` 1,102; `api.ts` 449-line monolithic client.
- Three lockfiles committed (bun.lock, package-lock.json, pnpm-lock.yaml).
- JWT in `localStorage` (finding #4).

## FE.1 ♻ Design system + skeleton — M — Fable 5

- Vite + React 18 + TS strict + Tailwind. **pnpm only**: delete `bun.lock` + `package-lock.json`, keep single `pnpm-lock.yaml`.
- New visual identity (this is the rebrand): neutral palette + one accent, per `claude.md` §5.
- Base `ui/` library: Button, Input, Select, Card, Badge, Modal, Table, Skeleton, Toast — documented, used everywhere.
- App shell (sidebar + topbar), router, auth context, protected routes.
- API client split by domain (`services/auth.ts`, `licitaciones.ts`, `query.ts`, ...) with typed responses and central error handling.
- Auth storage: httpOnly cookie if backend session endpoint is ready; else keep bearer token but isolate in one module for later swap.

**Acceptance:** skeleton runs; old `frontend/src/` deleted; UI components documented (Storybook or MD).

## FE.2 ♻ Core flows — L — Opus 4.8

Login · licitaciones list (filters by estado comercial + deadline, overdue in red) · create licitación + upload (uses the new SAS flow from task 1.1) · detail tabs: Resumen, Documentos (SAS view-url flow), Requisitos, Match Score · processing-queue page.

**Acceptance:** feature parity with old SPA for these flows; ≥1 vitest+RTL test per page; responsive.

## FE.3 ♻ Chat + Memoria — L — Opus 4.8

- Chat tab: session threads sidebar (list/open/new via `crypto.randomUUID()`), Markdown rendering **without** raw-HTML injection (no rehype-raw), clickable citations.
- Memoria flow: esquema proposal → chat refine → propuesta document → editor → export.
- Document editor: **spec the pagination requirement first**, then evaluate TipTap/ProseMirror vs re-doing the custom paginator. The old editor's margin-based page-break logic is documented in the old CHANGELOG (2026-06-23 entry) — learn from the bug history, don't port the code.

**Acceptance:** feature parity; editor monolith replaced by composable modules; tests.

## FE.4 Settings + admin + polish — M — Sonnet 5

- Settings: company profile form, reference templates upload/manage.
- Audit/analytics page against the new 1.6/5.2 endpoints (admin-only).
- Full responsive pass (mobile viewport usable), loading skeletons, empty states, error states with recovery actions.

**Acceptance:** every page has ≥1 test; narrow-viewport walkthrough clean.

---

Sequencing: FE runs after Phase 2, before Phase 3 (so org/admin screens in 3.5 are built once, in the new codebase). If task 1.1 lands before FE, patch old `blobStorage.ts` minimally in the interim.

Done when: old `frontend/src/` gone (inventory row ticked), parity confirmed page-by-page against a checklist written during spec.

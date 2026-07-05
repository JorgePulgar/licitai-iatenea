# Spec DM — Demo-minimal milestone (first sellable demo, months before the selling gate)

> Fable-written spec, 2026-07-05. Implementer: Opus 4.8. Review checklist at end.
> Problem it solves (red-team H1): the selling gate (full FE parity + 100% inventory) is 4–8 months of evenings away. Phase-B demos (personalized pliego demo — the GTM wedge) don't need the selling gate; they need a **demo-safe build**: the DEMO PATH rewritten (IP rule ♻ applies to anything shown or run commercially, demos included) + a minimal new FE. Everything else waits.
> This spec re-sequences existing tasks; it invents almost no new work.

## 1. What a Phase-B demo requires (and nothing more)

Demo choreography (see thinking-repo sales assets): upload THEIR pliego → checklist with citations → 2 chat questions (one answerable, one not → "no lo encuentro") → match score vs a company profile → memoria esquema + one drafted section on screen. Jorge drives; client watches. Single org, single user, Jorge's dev Azure env.

## 2. Scope — IN (ordered)

> **Progress tracking**: tick the Done column (☐→✅ + date) in the SAME commit that completes each task. This table is the milestone's source of truth across sessions.

| # | Work | Source task | Size | Done | Notes |
|---|---|---|---|---|---|
| DM1 | Audit endpoint fix | 1.6 | S | ✅ 2026-07-05 | already first in plan |
| DM2 | Query endpoint rewrite ♻ | 1.7 | S–M | ✅ 2026-07-05 | demo path, co-authored today |
| DM3 | Hardened prompts applied | 1.8 | S | ☐ | texts ready in `prompts-hardened.md`; a hostile pliego must not wreck a live demo |
| DM4 | Requirements + match rewrite ♻ | 5.5 pulled forward | M | ☐ | keep the spec'd improvements (asyncio.gather, page validation) — they're cheap and demo-visible (speed) |
| DM5 | Memoria service rewrite ♻ (`services/memoria.py` + `endpoints/memoria.py`) | 4.1 ♻-scope only | M | ☐ | synchronous execution — NO queue/worker; esquema + section drafting + chat refine. Export (5.6) OUT: show the draft rendered on screen. **Latency rule (red-team R2)**: section generation MUST stream tokens to the FE or complete in <20 s — a silent 45 s request dies in live demos AND risks HTTP timeouts. If neither is cheap, the demo runs on pre-generated sections + live chat-refine (fast path), per the demo script |
| DM6 | Perfil endpoint rewrite ♻, single-profile | 3.1 partial | S | ☐ | user-scoped as today; NO org model, NO migration — demo env has one user (Jorge). Org columns come later per spec-3.1 unchanged |
| DM7 | **FE-minimal**: new SPA, 5 screens | FE.1 + FE.2/FE.3 subset | L | ☐ | see §3 |
| DM8 | Memoria quality prompts applied | spec-memoria-prompts.md | S | ☐ | the drafted section is the demo's climax — quality prompts before first demo |
| DM9 | Eval-lite green | spec-5.3 subset | M | ☐ | golden set of 3 pliegos, suites S3 (faithfulness) + S4 (refusal) only; run before first real demo — the "no lo encuentro" moment must be reliable, not lucky |

## 3. FE-minimal (DM7) — exact scope

From spec-fe-design (design system, pnpm-only, httpOnly-or-isolated-token rule):
1. **Login** (existing auth, no reset/invites — Jorge only).
2. **Licitaciones list** (create + open; no filters beyond estado, no pipeline analytics).
3. **Upload + processing view** (spec-1.1 SAS flow if landed; else server-side upload — acceptable for demo env, note the debt).
4. **Detail: Requisitos + Chat tabs** (checklist with citation links to page refs; chat with clickable [p. X] — citations must at least show the page context; full PDF viewer optional/stretch).
5. **Memoria view**: esquema, generate section, chat-refine, rendered Markdown. NO TipTap/editor, NO export, NO pagination.

Explicitly OUT of FE-minimal: settings, admin, audit/analytics pages, org/user management, responsive polish beyond "usable on a laptop projector", Storybook. Tests: 1 smoke test per screen (not the ≥1-per-page parity bar — that returns at Phase FE proper).

**FE-minimal is a strict subset of Phase FE, not throwaway**: same design system, same API client structure, same component library seeds. Phase FE later = extend, not rewrite.

## 4. Scope — OUT (resist the creep)

Bicep/CI (demo runs on the existing dev env) · org model migration · queue/worker · auth flows (invites/reset) · PLACSP URL import (wow-factor stretch ONLY if DM1–9 done early) · exports · analytics · rate limiting (demo env, Jorge-driven) · Managed Identity migration (1.4) — dev env keeps keys until Phase 2, documented debt.

## 5. Inventory effect (IP)

DM completes these rewrite-inventory rows: `endpoints/query.py`, `services/requirements.py`+`prompts/requirements.py`+`prompts/match.py`, `services/memoria.py`+`endpoints/memoria.py`, `endpoints/perfil.py`, `frontend/src/**` (minimal replacement counts ONLY when old SPA is deleted — delete it at DM7 merge; the old build must not be what runs). That is 5 of 18 rows + the biggest one (frontend) structurally replaced. **Demo-safe ≠ selling gate**: remaining rows still block selling; demos are fine because everything executed/shown in the demo is rewritten code.

## 6. Sequence & rough calendar (evenings/weekends pace — adjust, but WRITE DATES)

- Week 1–2: DM1, DM2, DM3 (small tasks, momentum)
- Week 3–4: DM4, DM6
- Week 5–7: DM5 + DM8
- Week 7–10: DM7 (the long pole; start design-system skeleton in week 5 in parallel if energy allows)
- Week 10–11: DM9 + dry-run demos ×2 on fixture pliegos
- **Target: first live Phase-B demo ~week 12 — best case.** Red-team R2-H2: weeks 1–6 collide with validation calls, job interviews, possibly a new job starting (velocity halves), and DM9 hides ~6 h of golden-set labeling plus building the judge runner (an M on its own). **Realistic range: 16–20 weeks. Recalibrate after DM1–DM3 actuals; cut scope, never slip dates silently.**

## 7. Acceptance

1. Full demo choreography executed end-to-end on a fixture pliego by Jorge in <15 min, zero errors, on the NEW frontend.
2. Old `frontend/src/` deleted from the repo.
3. `rg` audit: no co-authored file among those executed in the demo path (inventory rows §5 ticked).
4. Eval-lite: faithfulness ≥0.95, refusal false-answers = 0 on the 3-pliego golden set.
5. Injection suite (1.8) passes against the live demo env.
6. A second person (or Jorge on a different machine/screen-share) has watched a dry run without the demo breaking.

## 8. Opus review checklist

- [ ] Every DM task implemented against its ORIGINAL spec (1.1/5.5/4.1♻/3.1-partial/fe-design) — this spec only re-scopes and re-orders; it never overrides their technical content.
- [ ] DM6 leaves the schema untouched (no org columns) — spec-3.1's migration arrives later intact.
- [ ] DM5 synchronous path is written so the 4.1 queue can wrap it later without rewriting (service function pure; endpoint calls it directly today, worker calls it tomorrow).
- [ ] Old SPA deletion is in the same PR that makes FE-minimal the served frontend.
- [ ] No new co-authored code imported into the demo path (grep imports of inventory files).
- [ ] Demo dry-run documented (date, pliego used, timing) before the milestone is declared done.

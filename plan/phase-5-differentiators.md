# Phase 5 — Differentiators (sell more, charge more)

> Prereq reading: `plan/00-CONTEXT.md` §2 (rewrite rules for ♻ tasks).

## 5.1 PLACSP integration — L — Opus 4.8

**Full design: `specs/spec-5.1-placsp.md`** (2026-07-04) — one parser core (`placsp_core`, lives in the Iatenea ops repo, vendored here at implementation time; already serving the GTM prospect DB), three consumers:
- Phase A: URL import (allowlisted download of PCAP+PPT+anexos → auto-create licitación → pipeline). Biggest wow-factor for the Spanish market.
- Phase B: Radar — per-org CPV/importe/geo watchlist, match-scored digests (capped + metered per spec-2.2b §5). The retention feature.

**Acceptance:** URL in → indexed licitación out with zero manual uploads; Radar digest test per spec §6.

## 5.2 ♻ Analytics dashboard — M — Sonnet 5

Completes the `audit.py` replacement started in 1.6, now org-scoped: win rate (`estado`/`resultado`), pipeline volume, deadlines calendar, per-user activity (admin view). Backend aggregates + frontend page (new codebase). **Acceptance:** renders from real data; org isolation test.

## 5.3 Model upgrade path + eval harness — L — Opus 4.8 (judges/core) + Sonnet 5 (runner/CI)

- Deployment names per env config (Bicep param → app setting), no hardcoded model constants (old code hardcodes `extraccion_datos_4o` etc. in services — clean these while touching).
- **Eval harness: full design in `specs/spec-5.3-eval.md`** (2026-07-04) — golden dataset, 7 metric suites (retrieval, answers, faithfulness, refusal, requirements recall, memoria quality, injection), LLM-judge with calibration, baseline + regression gating in CI, `--compare` for model swaps. Replaces `scripts/eval_rag.py` after parity.
- **Sizing note**: the golden-dataset labeling (~2h/pliego, Jorge) can start any time — it's independent of code and the highest-leverage manual work in the plan.

**Acceptance:** per spec §7 — switching chat model = config change + side-by-side eval report; prompt changes gated by the full suite.

## 5.4 Per-org usage report — M — Sonnet 5

Monthly usage per org: queries, tokens (persisted since 1.7), documents processed, DI pages. Surfaced in admin UI + optional email. Feeds your pricing/upsell conversations. **Acceptance:** report matches App Insights/DB numbers on a seeded env.

## 5.5 ♻ Rewrite requirements feature — M — Opus 4.8 — ✅ 2026-07-05 (pulled forward as DM4; see CHANGELOG)

Replaces `services/requirements.py`, `prompts/requirements.py`, `prompts/match.py`. Improvements to spec in:
- **Parallel retrieval**: the old code runs 18 hybrid searches sequentially — `asyncio.gather` them (~18× latency win).
- Regenerate/invalidate: `POST /requirements/regenerate` + auto-invalidate cache when documents change (old cache is stale forever).
- Validate extracted `pagina` against real page counts (citation trust, CLAUDE.md §8).
- Enforced category enum + `es_obligatorio` with confidence, dedup kept.
- Runs on the 4.1 worker if long.

**Acceptance:** generation ≤ ~1/10 of old latency on same corpus; regenerate works; invalid pages dropped; tests.

## 5.6 ♻ Rewrite export service — M — Opus 4.8 — ✅ 2026-07-18 (see CHANGELOG)

Replaces `services/memoria_export.py`. WeasyPrint from spec (keep the table/figure `break-after: avoid` learnings — documented in old CHANGELOG 2026-06-23 — as spec requirements, not copied code). Add: DOCX export (python-docx already a dep), configurable header/footer (company name/logo), optional TOC. **Acceptance:** PDF+DOCX export of a multi-page memoria with tables; captions never orphaned.

---

Done when: inventory rows for 5.5/5.6 files ticked → **rewrite inventory 100%** → lawyer consult (4.5) → selling gate open.

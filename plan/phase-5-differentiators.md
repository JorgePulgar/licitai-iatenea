# Phase 5 — Differentiators (sell more, charge more)

> Prereq reading: `plan/00-CONTEXT.md` §2 (rewrite rules for ♻ tasks).

## 5.1 PLACSP integration — L — Opus 4.8

Paste a PLACSP expediente URL → backend fetches the pliego PDFs → auto-creates the licitación → pipeline indexes. Biggest wow-factor for the Spanish market.
- Phase A: URL import (parse PLACSP detail page / its data endpoints, download PCAP+PPT+anexos).
- Phase B (later): CPV-code watchlist per org + email alerts on new matching tenders.

**Acceptance:** URL in → indexed licitación out with zero manual uploads.

## 5.2 ♻ Analytics dashboard — M — Sonnet 5

Completes the `audit.py` replacement started in 1.6, now org-scoped: win rate (`estado`/`resultado`), pipeline volume, deadlines calendar, per-user activity (admin view). Backend aggregates + frontend page (new codebase). **Acceptance:** renders from real data; org isolation test.

## 5.3 Model upgrade path — M — Sonnet 5

- Deployment names per env config (Bicep param → app setting), no hardcoded model constants (old code hardcodes `extraccion_datos_4o` etc. in services — clean these while touching).
- Eval harness: extend `scripts/eval_rag.py` into a repeatable before/after report.

**Acceptance:** switching chat model = config change + eval report, no code edit.

## 5.4 Per-org usage report — M — Sonnet 5

Monthly usage per org: queries, tokens (persisted since 1.7), documents processed, DI pages. Surfaced in admin UI + optional email. Feeds your pricing/upsell conversations. **Acceptance:** report matches App Insights/DB numbers on a seeded env.

## 5.5 ♻ Rewrite requirements feature — M — Opus 4.8

Replaces `services/requirements.py`, `prompts/requirements.py`, `prompts/match.py`. Improvements to spec in:
- **Parallel retrieval**: the old code runs 18 hybrid searches sequentially — `asyncio.gather` them (~18× latency win).
- Regenerate/invalidate: `POST /requirements/regenerate` + auto-invalidate cache when documents change (old cache is stale forever).
- Validate extracted `pagina` against real page counts (citation trust, claude.md §8).
- Enforced category enum + `es_obligatorio` with confidence, dedup kept.
- Runs on the 4.1 worker if long.

**Acceptance:** generation ≤ ~1/10 of old latency on same corpus; regenerate works; invalid pages dropped; tests.

## 5.6 ♻ Rewrite export service — M — Opus 4.8

Replaces `services/memoria_export.py`. WeasyPrint from spec (keep the table/figure `break-after: avoid` learnings — documented in old CHANGELOG 2026-06-23 — as spec requirements, not copied code). Add: DOCX export (python-docx already a dep), configurable header/footer (company name/logo), optional TOC. **Acceptance:** PDF+DOCX export of a multi-page memoria with tables; captions never orphaned.

---

Done when: inventory rows for 5.5/5.6 files ticked → **rewrite inventory 100%** → lawyer consult (4.5) → selling gate open.

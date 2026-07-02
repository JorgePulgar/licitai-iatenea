# LicitAI → Commercial Product — Analysis & Development Plan

> Generated 2026-07-02, updated 2026-07-02 with IP rewrite strategy.
> Target: sell to Spanish companies that bid on public tenders.
> Deployment model: **one Azure environment per client**. Sales motion: **self-service** (client operates, you maintain).
> Codebase: TFM repo frozen (`tfm-final`) and shared with Integra; commercial work happens here.
> **This document must never land in the repo shared with Integra.**

---

## 1. Codebase verdict

Solid TFM. Not sellable yet. Core RAG pipeline is good: hybrid search (keyword + vector + semantic ranker), inline citations with validation, isolation filters, Key Vault secrets, App Insights telemetry, configurable retention job. Gaps: security holes, zero deployment automation, no self-service user lifecycle, single-user data model — **and co-authored code that must be replaced before selling (see §2).**

---

## 2. IP strategy: full rewrite of co-authors' code

### 2.1 Decision (2026-07-02)

No consent will be sought from co-authors. Their code will be **replaced, not refactored**. Refactoring produces a derivative work and their copyright survives it; only new code written from a functional spec is clean. Features, architecture ideas, and DB schemas are not copyrightable — the concrete code expression is.

**Authorship audit (git blame on tfm-final, surviving lines):**

| Author | Frontend | Backend | Notes |
|---|---|---|---|
| Jorge Pulgar | 418 (4%) | 3,853 (53%) | — |
| Siro (DavisuaCoder + sicora-dev) | 9,240 (96%) | ~2,900 (40%) | Whole frontend + several complete backend modules |
| Álvaro (alvarolopred + alvarixu) | 0 | ~560 (8%) | Scattered through core RAG services |

### 2.2 Rules of the rewrite (every task in §6 that touches inventory files)

1. **Never edit their file into shape.** Write a short functional spec (endpoints, inputs/outputs, behavior), delete the old file, reimplement from the spec. Different structure, naming, and organization are expected — the improvements listed per file below force this naturally.
2. **Full-file replacement even for partial authorship.** A file that is 30% theirs is rewritten whole.
3. Track progress in the §2.3 inventory. **Do not sell or distribute until every row is done.**
4. Residual risk caveat: the product's development *started* from a co-authored base; a purist would argue lineage. A one-hour lawyer consult after the rewrite is cheap insurance. Not legal advice.

### 2.3 Rewrite inventory

**A. Whole modules (theirs ~100%) — delete + reimplement from spec:**

| File | Lines | Rewritten in task | Status |
|---|---|---|---|
| `frontend/src/**` (entire SPA) | ~9,200 | Phase FE | ☐ |
| `backend/app/services/templates.py` | 443 | 3.2b | ☐ |
| `backend/app/services/requirements.py` | 229 | 5.5 | ☐ |
| `backend/app/services/memoria_export.py` | 278 | 5.6 | ☐ |
| `backend/app/api/v1/endpoints/audit.py` | 212 | 1.6 + 5.2 | ☐ |
| `backend/app/api/v1/endpoints/templates.py` | 124 | 3.2b | ☐ |
| `backend/app/api/v1/endpoints/perfil.py` | 96 | 3.1 | ☐ |
| `backend/app/api/v1/endpoints/query.py` | 227 | 1.7 | ☐ |
| `backend/app/prompts/templates.py` + `prompts/requirements.py` | 150 | 3.2b / 5.5 | ☐ |
| `backend/app/prompts/match.py` (63/81) | 81 | 5.5 | ☐ |

**B. Partially theirs — full-file rewrite folded into the phase that touches them:**

| File | Their lines | Rewritten in task | Status |
|---|---|---|---|
| `endpoints/licitaciones.py` | 268/511 | 1.1 + 3.1 | ☐ |
| `services/memoria.py` | 239/1006 | 4.1 | ☐ |
| `models/schemas.py` | ~180/409 | 3.1 | ☐ |
| `models/domain.py` | ~165/324 | 3.1 (org model = new schema anyway) | ☐ |
| `services/indexing.py` | 138 | 3.1 (org_id index field) | ☐ |
| `services/embeddings.py` | 100 | 1.4 (managed identity clients) | ☐ |
| `services/ocr.py` | 89 | 4.1 (worker refactor) | ☐ |
| `core/config.py` | 87 | 1.4 (factory refactor) | ☐ |
| `services/pipeline.py` | 46 | 4.1 (queue worker replaces it) | ☐ |
| `db/database.py` | 46 | 2.4 (Alembic wiring) | ☐ |
| `endpoints/memoria.py` | 84/326 | 4.1 | ☐ |
| `app/main.py` | 31 | 1.3 (middleware additions) | ☐ |
| `services/ingestion.py` | 24 | 1.1 (SAS redesign) | ☐ |

**Verification gate before first sale:** every row checked; spot-check a sample of rewritten files against the `tfm-final` originals for structural similarity (they should read as different programs implementing the same feature).

---

## 3. Non-code blockers

### 3.1 Secret hygiene — DONE 2026-07-02
gitleaks full-history scan: clean (85 commits). Key rotation deferred (clean scan). `tfm-final` tag pushed at `6dfbe76`.

### 3.2 Co-ownership — superseded by §2 rewrite strategy.

---

## 4. Critical security findings (fix before any client)

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | **Container-level SAS sent to browser.** Any logged-in user can read/write/delete ANY blob in the container | `frontend/src/services/blobStorage.ts`, SAS endpoint | Per-blob SAS scoped to `{licitacion_id}/` path, write-only, ≤15 min TTL, or backend-proxied upload |
| 2 | **`GET /api/v1/system/audit` has NO authentication.** Exposes all users' emails, names, per-user usage, token counts to anyone who can reach the API | `backend/app/api/v1/endpoints/audit.py:83` | Task 1.6. Also present in the TFM repo shared with Integra — consider warning them |
| 3 | No rate limiting anywhere. Login brute-forceable; `/query` = uncapped OpenAI bill | all endpoints | `slowapi`: 5/min login, caps on LLM endpoints |
| 4 | JWT in `localStorage` (XSS exposure) | `frontend/src/services/api.ts` | CSP header short-term; httpOnly cookie in Phase FE rewrite |
| 5 | Key-based auth to Search/Storage/DI/OpenAI | `core/config.py` | Managed Identity + RBAC (task 1.4) |
| 6 | No password reset, lockout, MFA | auth | Phase 3 |
| 7 | Prompt injection: pliego text is untrusted LLM input | query/summary/memoria | Harden prompts, keep citation validation, document residual risk |

## 4b. Code-quality findings from the co-author code review (folded into rewrite tasks)

- `endpoints/query.py`: silent `except Exception` on persistence (no logging — violates own conventions); **never persists `tokens_prompt`/`tokens_completion`/`latency_ms`** though the columns exist (telemetry loss); sessions listing does N+1 query per session; history endpoint unpaginated.
- `endpoints/audit.py`: no auth (finding #2); N+1 per user; response schemas defined in the endpoint file instead of `models/schemas.py`.
- `services/requirements.py`: 18 hybrid searches run **sequentially** (should be `asyncio.gather` — ~18× latency); cache has no invalidation or regenerate option (stale forever after re-upload); extracted `pagina` never validated against real page counts; category values unenforced; fresh-session workaround papers over the sync-pipeline root cause (fixed properly by 4.1).
- `services/templates.py`: synchronous Azure DI + Blob calls inside `async` path (blocks the event loop); DI text-extraction logic duplicates `ocr.py` (DRY); no retry/backoff on Azure calls (violates own conventions); no file-size cap on uploads; per-user isolation should become org-wide sharing (3.1).
- `endpoints/perfil.py`: single-profile-per-user hardcoded (`first()`), silent ambiguity if multiple exist; JSON-in-Text columns.
- Frontend: **zero tests**; `components/ui/` has only 5 components (no Button/Input/Card — buttons/inputs restyled inline everywhere, against own CLAUDE.md §5); `RichDocumentEditor.tsx` 1,359 lines, `MemoriaTab.tsx` 1,102, `api.ts` 449-line monolith; **three lockfiles committed** (bun.lock, package-lock.json, pnpm-lock.yaml).

---

## 5. Which Claude model per task

- **Fable 5** — security design, auth refactors, tenant/org data model, IaC architecture; design + diff-review on critical tasks (1.1, 1.4, 2.2, 3.1, 4.1, FE.1).
- **Opus 4.8** — complex multi-file implementation from a clear spec: migrations, queue workers, auth flows, integrations, module rewrites.
- **Sonnet 5** — standard well-specified tasks: CRUD, UI pages, CI, docs, dashboards. Default workhorse.
- **Haiku 4.5** — mechanical single-file edits.

Pattern for rewrite tasks: **spec with Fable → implement with Opus/Sonnet → Fable reviews the diff against the spec (not against the old file).**

---

## 6. Development plan

Sized S (≤1 day), M (2–4 days), L (1–2 weeks). Tasks marked ♻ are rewrite-inventory tasks (rules §2.2 apply).

### Phase 0 — Handover + fork — ✅ DONE 2026-07-02

0.1 secret scan (clean) · 0.2 `tfm-final` tag pushed · 0.3 fork + rebrand pushed to `licitai-iatenea` · 0.4 replaced by §2 rewrite strategy.

### Phase 1 — Security hardening

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 1.1 ♻ | M | **Fable 5** | Blob SAS fix (finding #1): per-blob/per-prefix SAS, write-only, short TTL or backend-proxied upload. Full rewrite of `services/ingestion.py` and upload paths in `endpoints/licitaciones.py` while here | Test proves user A's SAS cannot touch user B's path |
| 1.2 | S | Sonnet 5 | `slowapi` rate limits: login 5/min/IP, query 20/min/user, upload 10/hour/user | 429 beyond limits |
| 1.3 ♻ | S | Sonnet 5 | Security headers middleware (HSTS, CSP, X-Content-Type-Options, X-Frame-Options). Rewrite `main.py` while adding it | Headers on all responses |
| 1.4 ♻ | M | **Fable 5** | Managed Identity for Search/Storage/OpenAI/DI; `config.py` rewritten as a settings factory (no import-time mutation); `services/embeddings.py` rewritten with the new client wiring + retry/backoff | Prod path works with zero keys except JWT/SQL |
| 1.5 | S | Haiku 4.5 | UUID validation before OData filter interpolation (`indexing.py`, `query.py`) | Malformed IDs → 400 |
| 1.6 ♻ | S | Opus 4.8 | **URGENT — rewrite `endpoints/audit.py`**: require auth + `admin` role; schemas move to `models/schemas.py`; single aggregate queries (kill N+1). Interim minimal endpoint; full analytics comes in 5.2 | Unauthenticated request → 401; non-admin → 403 |
| 1.7 ♻ | M | Opus 4.8 | **Rewrite `endpoints/query.py`**: persist tokens + latency, log persistence failures, fix sessions N+1 (window function or single grouped query), paginate history, keep session semantics | Telemetry columns populated; no silent excepts; tests |

### Phase 2 — Deployability (unchanged from v1)

| Task | Size | Model | Description |
|---|---|---|---|
| 2.1 | M | Sonnet 5 | Dockerfile backend (multi-stage) + frontend build + docker-compose dev |
| 2.2 | L | **Fable 5** design → Opus 4.8 | Bicep per-client stack: RG, SQL S0, Storage (soft-delete), AI Search Basic, DI, Azure OpenAI (Sweden/Spain Central), KV, App Insights, Container Apps, Static Web App, Managed Identity + RBAC. `az deployment sub create` → env from nothing |
| 2.3 | M | Sonnet 5 | GitHub Actions: ruff + pytest + frontend build on PR; per-env deploy workflow |
| 2.4 ♻ | M | Opus 4.8 | Reintroduce Alembic (baseline from current schema, runs in deploy). Rewrite `db/database.py` with the new engine/session wiring |
| 2.5 | S | Haiku 4.5 | `create-org-admin` CLI |
| 2.6 | S | Sonnet 5 | Cost tagging + budget alerts in Bicep |

Fixed cost per client env ≈ €100–150/month + usage. Price maintenance accordingly.

### Phase FE — Frontend rebuild (new; replaces Siro's SPA, doubles as rebrand)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| FE.1 ♻ | M | **Fable 5** | Design system + app skeleton from spec: Vite + React 18 + TS strict + Tailwind, **pnpm only** (single lockfile), base `ui/` library (Button, Input, Card, Badge, Modal, Table, Skeleton), layout shell, router, auth context, typed API client split by domain. Visual identity = new brand, per CLAUDE.md §5 (sober, Linear/Notion-like, responsive) | Skeleton runs; old `src/` deleted; component library documented |
| FE.2 ♻ | L | Opus 4.8 | Core flows: login, licitaciones list + filters, create/upload (new SAS flow from 1.1), detail tabs (resumen, documentos, requisitos, match) | Feature parity with old SPA, tests per page |
| FE.3 ♻ | L | Opus 4.8 | Chat tab (sessions sidebar, citations) + Memoria flow (esquema → propuesta → chat edit → export). Document editor: evaluate replacing the 1,359-line custom editor with TipTap/ProseMirror-based implementation — spec the pagination requirement first | Feature parity; editor monolith gone |
| FE.4 | M | Sonnet 5 | Settings (company profile, templates upload), audit/analytics page (against new 1.6/5.2 endpoints), vitest + RTL suite, responsive pass | ≥1 test per page; mobile viewport usable |

### Phase 3 — Self-service product

| Task | Size | Model | Description |
|---|---|---|---|
| 3.1 ♻ | L | **Fable 5** | Organization model (`organizations`, `users.org_id`, org_id on licitaciones/profiles/templates, AI Search `org_id` field + reindex, roles admin/member). Rewrites `models/domain.py`, `models/schemas.py`, `endpoints/perfil.py` (org-scoped, multi-profile), `services/indexing.py`, remaining `endpoints/licitaciones.py` |
| 3.2a | M | Sonnet 5 | Email service (Azure Communication Services): invite, reset, deadline templates |
| 3.2b ♻ | M | Opus 4.8 | **Rewrite templates feature** (`services/templates.py`, `endpoints/templates.py`, `prompts/templates.py`): async Azure clients (no event-loop blocking), reuse `ocr.py` extraction (kill duplication), retry/backoff, file-size caps, org-wide sharing, regenerate-summary endpoint |
| 3.3 | M | Opus 4.8 | Invite flow (tokenized email link → set password) |
| 3.4 | S | Opus 4.8 | Password reset (tokenized, 1h, single-use) |
| 3.5 | M | Sonnet 5 | Admin settings UI (user list, invite, deactivate, role) — lands in Phase FE codebase |
| 3.6 | M | Sonnet 5 | Deadline alert emails (7/3/1 days) |

### Phase 4 — Reliability

| Task | Size | Model | Description |
|---|---|---|---|
| 4.1 ♻ | L | Opus 4.8 + **Fable 5** review | Queue-based pipeline (Azure Storage Queue + worker container, stuck-job recovery). Replaces `services/pipeline.py`; rewrites `services/ocr.py` and the memoria generation orchestration (`services/memoria.py`, `endpoints/memoria.py`) onto the worker. This also removes the fresh-session workaround pattern |
| 4.2 | M | Sonnet 5 | App Insights alerts + availability test |
| 4.3 | S | Haiku 4.5 | Deep health endpoint |
| 4.4 | S | Sonnet 5 | Runbooks (restore, reindex, rotate, onboard) |
| 4.5 | S | Fable 5 + lawyer | GDPR sales pack. Add the §2.2 rewrite-completion sanity check to the same lawyer consult |

### Phase 5 — Differentiators

| Task | Size | Model | Description |
|---|---|---|---|
| 5.1 | L | Opus 4.8 | PLACSP integration (URL → auto-import; later CPV watchlist + alerts) |
| 5.2 ♻ | M | Sonnet 5 | Analytics dashboard (win rate, volume, deadlines) on the rewritten audit/usage endpoints — completes the `audit.py` replacement with org scoping |
| 5.3 | M | Sonnet 5 | Model upgrade path (per-env deployment names, eval before switch) |
| 5.4 | M | Sonnet 5 | Per-org usage report (tokens now persisted thanks to 1.7) |
| 5.5 ♻ | M | Opus 4.8 | **Rewrite requirements feature** (`services/requirements.py`, `prompts/requirements.py`, `prompts/match.py`): parallel multi-query retrieval (`asyncio.gather`), regenerate/invalidate endpoint, page-citation validation against real page counts, enforced category enum, obligatorio/optional confidence |
| 5.6 ♻ | M | Opus 4.8 | **Rewrite export service** (`services/memoria_export.py`): WeasyPrint from spec + add DOCX export (python-docx already a dep), header/footer/TOC options |

---

## 7. Order

1. **1.6 first** (unauthenticated audit endpoint — worst live hole) → rest of Phase 1 → Phase 2 → **Phase FE** (biggest inventory chunk + rebrand) → 3 → 4 → 5.
2. Selling gate: §2.3 inventory 100% checked + lawyer consult (4.5).
3. Phase FE before Phase 3 UI tasks so admin/org screens are built once, in the new codebase.

## 8. Refactors folded in

`config.py` factory (1.4) · Alembic (2.4) · delete dead `endpoints/pliegos.py` stub · editor monolith replaced (FE.3) · single pnpm lockfile (FE.1).

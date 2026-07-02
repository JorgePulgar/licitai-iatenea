# LicitAI → Commercial Product — Analysis & Development Plan

> Generated 2026-07-02. Target: sell to Spanish companies that bid on public tenders.
> Deployment model: **one Azure environment per client**. Sales motion: **self-service** (client operates, you maintain).
> Codebase strategy: TFM repo frozen and shared with Integra; commercial work continues in this private repo (rebrand).
> **This document must never land in the repo shared with Integra.**

---

## 1. Codebase verdict

Solid TFM. Not sellable yet. Core RAG pipeline is good: hybrid search (keyword + vector + semantic ranker), inline citations with validation, `user_id`/`licitacion_id` isolation filters, Key Vault secrets, App Insights telemetry, configurable retention job. Gaps: security holes, zero deployment automation, no self-service user lifecycle, single-user data model.

---

## 2. Non-code blockers (do before anything else)

### 2.1 Co-ownership ⚠️ BLOCKS ALL SALES
Code written by 3 developers (Álvaro, Jorge, Siro). No IP was signed away to Integra — but teammates co-own their contributions by default under Spanish IP law. Selling without a written agreement from them is a lawsuit risk.

- Get a signed agreement (assignment or revenue share) **before** the first sale.
- Check the master program's IP rules (Tajamar).
- Not legal advice — spend a few hundred € on a lawyer here. Worth it.

### 2.2 Secret hygiene at handover
Before sharing the TFM repo with Integra:

- Scan full git history for leaked secrets (`gitleaks detect --source .`).
- Rotate ALL Azure keys + JWT secret + SQL credentials.
- Move Integra to their own Key Vault / subscription. The shared dev DB must stop being shared.

---

## 3. Critical security findings (fix before any client)

| # | Issue | Where | Fix |
|---|---|---|---|
| 1 | **Container-level SAS sent to browser.** Any logged-in user can read/write/delete ANY blob in the container — other users' pliegos included | `frontend/src/services/blobStorage.ts`, SAS endpoint in backend | Per-blob SAS scoped to `{licitacion_id}/` path, write-only, ≤15 min TTL. Or proxy uploads through the backend |
| 2 | No rate limiting anywhere. Login is brute-forceable; `/query` endpoint = uncapped OpenAI bill | all endpoints | `slowapi`: 5/min on login, sane caps on LLM endpoints |
| 3 | JWT stored in `localStorage` (XSS exposure) | `frontend/src/services/api.ts:24` | Acceptable short-term; add strict CSP header. Later: httpOnly cookie |
| 4 | Key-based auth to Search/Storage/Document Intelligence/OpenAI | `backend/app/core/config.py` KV secrets | Managed Identity + RBAC in prod (`DefaultAzureCredential` pattern already exists for KV). Removes per-client key rotation burden |
| 5 | No password reset, no account lockout, no MFA | auth | Phase 3 (needs email service) |
| 6 | Prompt injection: pliego text is untrusted LLM input | query/summary/memoria services | Cannot fully solve. Harden system prompts, keep citation validation (LIC-057), document residual risk |

---

## 4. Which Claude model per task

Rule of thumb:

- **Fable 5** — only where a subtle mistake means a data leak, broken isolation, or an unrecoverable client env: security design, auth refactors, tenant/org data model, IaC architecture. Expensive; use surgically.
- **Opus 4.8** — complex multi-file implementation with clear spec: migrations, queue workers, auth flows, integrations.
- **Sonnet 5** — standard well-specified tasks: CRUD, UI pages, CI pipelines, docs, dashboards. Default workhorse.
- **Haiku 4.5** — mechanical single-file edits: headers middleware, input validation, small endpoints.

Pattern that works: **design with Fable, implement with Opus/Sonnet, review the diff with Fable** on the critical tasks (1.1, 1.4, 2.2, 3.1, 4.1).

Phase 0 does NOT need Fable — it is mechanical or human-only work.

---

## 5. Development plan — 6 phases

Sized S (≤1 day), M (2–4 days), L (1–2 weeks). Each task is self-contained → hand one task per session to the assigned model.

### Phase 0 — Handover + fork (now, before sharing with Integra)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 0.1 | S | Sonnet 5 + you | Run `gitleaks` on full history; model builds rotation checklist. **You** rotate keys in Azure portal/CLI — never paste live secrets into a model session | No live secret in history; all keys rotated |
| 0.2 | S | Manual (or Haiku 4.5) | Freeze TFM repo: tag `tfm-final`, share with Integra | Tag exists; Integra has snapshot only |
| 0.3 | M | Sonnet 5 | Private fork + rebrand: new name, strip TFM/Tajamar/Integra references from code/docs/UI, new Azure subscription for commercial work | Grep for old names returns nothing user-visible |
| 0.4 | — | Lawyer (Fable 5 drafts outline) | Sign co-ownership agreement with teammates | Signed document |

### Phase 1 — Security hardening

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 1.1 | M | **Fable 5** | Blob SAS fix (finding #1): per-blob or per-prefix SAS, write-only, short TTL — or backend-proxied upload. Isolation-critical design | Test proves user A's SAS cannot touch user B's path |
| 1.2 | S | Sonnet 5 | `slowapi` rate limits: login 5/min/IP, query 20/min/user, upload 10/hour/user | 429 beyond limits; test covers login |
| 1.3 | S | Haiku 4.5 | Security headers middleware: HSTS, CSP, X-Content-Type-Options, X-Frame-Options | Headers present on all responses |
| 1.4 | M | **Fable 5** (Opus 4.8 acceptable) | Managed Identity for Search + Storage + OpenAI + Document Intelligence in prod path; keys stay as dev fallback. Refactor `config.py`: stop mutating `Settings` at import time, use a factory (makes this testable) | Prod path works with zero keys in KV except JWT/SQL |
| 1.5 | S | Haiku 4.5 | Validate OData filter inputs before interpolation (`indexing.py` delete filter, `query.py` filters): UUID regex check | Malformed IDs rejected with 400 |

### Phase 2 — Deployability (the revenue engine: repeatable per-client envs)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 2.1 | M | Sonnet 5 | `Dockerfile` backend (multi-stage, uvicorn) + frontend build. Local `docker-compose` for dev | `docker compose up` runs the stack locally |
| 2.2 | L | **Fable 5** design → Opus 4.8 implement | **Bicep templates**: `main.bicep` + params file per client. Provisions: resource group, Azure SQL (S0), Storage (soft-delete on), AI Search (Basic), Document Intelligence, Azure OpenAI (Sweden Central or Spain Central — EU data residency is the sales pitch), Key Vault, App Insights, Container Apps (backend), Static Web App (frontend). Managed Identity wiring + RBAC assignments included | `az deployment sub create` → working env from nothing |
| 2.3 | M | Sonnet 5 | GitHub Actions: ruff + pytest + frontend build on PR; deploy workflow per client env (matrix or manual dispatch with env param) | Green pipeline; one-click deploy to named env |
| 2.4 | M | Opus 4.8 | **Reintroduce Alembic.** Reverses the CLAUDE.md §15 no-migrations decision — justified: N client DBs, manual ALTER doesn't scale past 1 env. Baseline migration from current schema; migrations run in deploy pipeline | `alembic upgrade head` idempotent on fresh + existing DB |
| 2.5 | S | Haiku 4.5 | Admin CLI: `create-org-admin` command (replaces dev-only `/register` for provisioning the first client user) | Command creates admin user against any env |
| 2.6 | S | Sonnet 5 | Per-client cost tagging + Azure budget alerts in Bicep | Budget alert email fires at threshold |

**Fixed cost per client env ≈ €100–150/month** (AI Search Basic ~€70 dominates; SQL S0 ~€13; Container Apps ~€15–30; Storage ~€1) + OpenAI/Document Intelligence usage. Price maintenance accordingly.

### Phase 3 — Self-service product (org model + user lifecycle)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 3.1 | L | **Fable 5** | **Organization model**: `organizations` table, `users.org_id`, `org_id` on `licitaciones`/`company_profiles`/`company_templates`. All DB queries + AI Search filters switch from `user_id` to `org_id` (add `org_id` field to index; reindex script pattern exists in `scripts/reindex_pliegos.py`). Roles: `admin` \| `member`. Highest regression risk in the plan — isolation touches every query | Two users in same org see same licitaciones; member cannot manage users; cross-org isolation test |
| 3.2 | M | Sonnet 5 | Email service: Azure Communication Services. Templates: invite, password reset, deadline alert | Emails delivered from client's env |
| 3.3 | M | Opus 4.8 | Invite flow: admin invites by email → tokenized link → set password. Removes the prod-registration problem | Invited user onboards without dev intervention |
| 3.4 | S | Opus 4.8 | Password reset flow (tokenized email link, 1h expiry, single-use) | Reset works; token single-use |
| 3.5 | M | Sonnet 5 | Admin settings page: user list, invite, deactivate, role change | Admin manages users without touching DB |
| 3.6 | M | Sonnet 5 | Deadline alerts: daily job emails upcoming `licitaciones.deadline` (7/3/1 days before). Column already exists | Alert emails fire on schedule |

### Phase 4 — Reliability (what makes the maintenance contract honest)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 4.1 | L | Opus 4.8 implement, **Fable 5** reviews design + diff | Replace FastAPI `BackgroundTasks` OCR pipeline with Azure Storage Queue + worker container (Container Apps, scale-to-zero). Current design: server restart mid-OCR = pliego stuck in `processing` forever, no retry. Add stuck-job recovery (processing > 30 min → error + requeue-able) | Kill worker mid-job → job retried, no stuck pliegos |
| 4.2 | M | Sonnet 5 | App Insights alerts: error rate, P95 latency, pipeline failures, availability ping on `/health`. Action group → your email | Synthetic failure triggers alert email |
| 4.3 | S | Haiku 4.5 | Deep health endpoint: checks SQL, Search, Storage, OpenAI reachability | `/health/deep` returns per-dependency status |
| 4.4 | S | Sonnet 5 | Runbooks (this repo): restore SQL PITR, rebuild Search index from blobs, rotate secrets, onboard new client | Each runbook executable start-to-finish |
| 4.5 | S | Fable 5 drafts → lawyer reviews | GDPR sales pack: DPA template, subprocessor list (Microsoft), data-flow diagram, per-client retention config (`RETENTION_DAYS` exists). One lawyer review, reused per client | Pack ready to attach to contracts |

### Phase 5 — Differentiators (sell more, charge more)

| Task | Size | Model | Description | Acceptance |
|---|---|---|---|---|
| 5.1 | L | Opus 4.8 | **PLACSP integration**: paste expediente URL → auto-download pliegos → auto-create licitación. Biggest wow-factor for the Spanish market. Later: CPV-code watchlist + new-tender email alerts | URL in → indexed licitación out, no manual upload |
| 5.2 | M | Sonnet 5 | Analytics dashboard: win rate (`estado`/`resultado` already modeled), pipeline volume, deadlines calendar | Dashboard renders from real data |
| 5.3 | M | Sonnet 5 | Model upgrade path: `gpt-4o-mini` is aging; make model deployment names per-env config; eval with `scripts/eval_rag.py` before switching | Model swap = config change + eval report |
| 5.4 | M | Sonnet 5 | Per-org usage report (tokens already logged per query) → transparency + upsell data | Monthly usage summary per client |

---

## 6. Refactors folded in

- `config.py` factory pattern (task 1.4).
- Alembic reintroduction (task 2.4).
- Delete dead `backend/app/api/v1/endpoints/pliegos.py` stub (129 B).
- Split 44 KB `frontend/src/components/RichDocumentEditor.tsx` when next touched.
- No big-bang rewrite needed — the architecture is sound.

## 7. Order

Phase 0 → 1 → 2 = demo-able + deployable for client #1.
Phase 3 = self-service.
Phase 4 = maintenance contract honest.
Phase 5 = sells clients #2–10.

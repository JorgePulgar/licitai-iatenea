# LicitAI Commercial — Development Context

> **Read this first in every session, then read ONLY the phase doc you're working on** (`plan/phase-*.md`).
> Private repo `licitai-iatenea` (local folder may be named `pliexa` — same repo, GitHub remote unchanged). This plan must never reach the TFM repo shared with Integra.
> **ACTIVE MILESTONE (decided 2026-07-05): demo-minimal** — `specs/spec-demo-minimal.md`, DM1→DM9. Development starts at DM1 (= task 1.6). The phase order below remains the map for everything after the milestone.

## 1. What this is

LicitAI: RAG platform for analyzing Spanish public tenders (pliegos PCAP/PPT → OCR → Azure AI Search → chat with citations, requirements checklist, match score, technical proposal drafts). Forked from a TFM (`tfm-final` tag in the old `licitai` repo); being turned into a commercial product.

- **Commercial name: Pliexa** (decided 2026-07-04). "LicitAI" remains only as the TFM's public name on jorgepulgar.com. Phase FE applies the rebrand: all UI-facing copy uses **Pliexa**; where specs/tasks say `licitai` in resource names/tags (e.g. spec-2.2), substitute `pliexa` for new resources. Internal code identifiers may keep `licitai` until their rewrite touches them. Domain (pliexa.com/.es) + OEPM/EUIPO trademark checks pending — folded into the selling-gate lawyer consult. Never state publicly that Pliexa is "based on" the TFM code (undermines the rewrite/lineage-distance strategy); experience-based framing only.
- **Business model (revised 2026-07-04 — two tiers, replaces dedicated-per-client default)**:
  - **Standard tier**: ONE shared Azure environment runs all standard clients; per-client isolation at the data plane — dedicated AI Search index per client (physical), dedicated blob container per client (physical), shared SQL DB with org_id filtering (spec-3.1 invariant). Full design: **spec-2.2b-shared-tier.md**. Marginal infra cost ≈ €20–40/month/client.
  - **Dedicated tier (premium)**: full per-client environment via Bicep (spec-2.2) at 2–3× monthly price — for bid-data-sensitive/compliance-driven buyers. Isolation is sold as a feature (bid data = competitive secrets).
  - **Build implication**: Phases 2/3 assume shared-by-default, dedicated-as-option. Bicep provisions both the shared env and dedicated envs (params distinguish them). Design multi-tenant now; don't retrofit.
  - Jorge provisions and maintains; clients operate self-service. Maintenance/SLA retainer revenue is independent of tier.
- **Positioning**: private RAG over the client's own corpus + pliego answering/drafting — NOT tender discovery (Tendios/Gobierto own that space). EU data residency + isolation are the GDPR sales pitch.
- **Stack**: FastAPI + SQLAlchemy + Azure SQL / React + Vite + TS + Tailwind / Azure OpenAI, AI Search, Document Intelligence, Blob, Key Vault, App Insights.
- Project conventions: see `CLAUDE.md` at repo root (terminology §7, RAG rules §9, security §10, UI style §5).

## 2. IP rewrite strategy (applies to every task marked ♻)

Co-authors (Siro, Álvaro) own ~96% of the frontend and ~47% of the backend by git blame. No consent will be sought; their code gets **replaced, not refactored**:

1. **Never edit their file into shape.** Write a short functional spec (endpoints, inputs/outputs, behavior), delete the old file, reimplement from the spec. Different structure and naming expected.
2. **Full-file replacement even for partial authorship** (a file 30% theirs is rewritten whole).
3. Tick the file off in the inventory below when done.
4. **Selling gate**: inventory 100% + one-hour lawyer consult (task 4.5).

### Rewrite inventory (master checklist)

| File | Task | Done |
|---|---|---|
| `frontend/src/**` (entire SPA) | Phase FE | ☐ |
| `services/templates.py` + `endpoints/templates.py` + `prompts/templates.py` | 3.2b | ☐ |
| `services/requirements.py` + `prompts/requirements.py` + `prompts/match.py` | 5.5 | ✅ 2026-07-05 (DM4; prompts clean-room, sin leer los antiguos) |
| `services/memoria_export.py` | 5.6 | ☐ |
| `endpoints/audit.py` | 1.6 (+5.2) | ✅ 2026-07-05 (rewrite 1.6; 5.2 lo extenderá) |
| `endpoints/perfil.py` | 3.1 | ☐ |
| `endpoints/query.py` | 1.7 | ✅ 2026-07-05 |
| `endpoints/licitaciones.py` | 1.1 + 3.1 | ☐ |
| `services/memoria.py` + `endpoints/memoria.py` | 4.1 | ☐ |
| `models/schemas.py` + `models/domain.py` | 3.1 | ☐ |
| `services/indexing.py` | 3.1 | ☐ |
| `services/embeddings.py` | 1.4 | ☐ |
| `services/ocr.py` | 4.1 | ☐ |
| `core/config.py` | 1.4 | ☐ |
| `services/pipeline.py` | 4.1 | ☐ |
| `db/database.py` | 2.4 | ☐ |
| `app/main.py` | 1.3 | ☐ |
| `services/ingestion.py` | 1.1 | ☐ |

## 3. Critical security findings (master list)

| # | Issue | Fixed by |
|---|---|---|
| 1 | Container-level SAS sent to browser — any user can touch any blob | 1.1 (spec-1.1-sas.md) |
| 1b | Client-supplied `blob_url` trusted; `download_pliego_bytes` accepts `file://` → local file read / cross-user blob read via pipeline | 1.1 (spec-1.1-sas.md §3.2–3.3) |
| 2 | `GET /api/v1/system/audit` unauthenticated — leaks all users' data | 1.6 (**do first**) |
| 3 | No rate limiting (login brute force, uncapped LLM bill) | 1.2 |
| 4 | JWT in localStorage | CSP (1.3) → httpOnly cookie (Phase FE) |
| 5 | Key-based auth to Azure services | 1.4 (Managed Identity) |
| 6 | No password reset / lockout / MFA | Phase 3 |
| 7 | Prompt injection via pliego text | mitigations only; document |

## 4. Which Claude model per task

- **Fable 5**: no longer required — all Fable design work was front-loaded as specs in `plan/specs/` (2026-07-02 spec sprint), each ending with an Opus review checklist.
- **Opus 4.8**: complex implementation from the specs (migrations, workers, auth flows, module rewrites) **and** diff reviews using each spec's checklist.
- **Sonnet 5**: standard tasks (CRUD, UI, CI, docs). Default.
- **Haiku 4.5**: mechanical single-file edits.

**Specs (read the one for your task, it overrides the phase doc's shorter description):**
`spec-1.1-sas.md` · `spec-1.4-config-mi.md` · `spec-2.2-bicep.md` · **`spec-2.2b-shared-tier.md` (2026-07-04 — two-tier amendment; read WITH 2.2 and 3.1)** · `spec-3.1-org-model.md` · `spec-4.1-queue.md` · **`spec-5.1-placsp.md` (2026-07-04 — PLACSP data layer: URL import + Radar + GTM prospect DB)** · **`spec-5.3-eval.md` (2026-07-04 — eval harness: golden dataset, faithfulness/refusal/requirements/memoria suites, regression gating)** · **`spec-demo-minimal.md` (2026-07-05 — DM milestone: earliest demo-safe build)** · **`spec-memoria-prompts.md` (2026-07-05 — flagship drafting prompts, ready-to-apply)** · `spec-fe-design.md` · `spec-auth-flows.md` (3.3/3.4) · `prompts-hardened.md` (task 1.8 — ready-to-apply prompt texts + injection tests).

Review pattern: implement from spec → review the diff **against the spec's checklist**, never against the old co-authored file.

## 5. Phase order & status

| Phase | Doc | Status |
|---|---|---|
| 0 — Handover + fork | (done, no doc) | ✅ 2026-07-02: gitleaks clean, `tfm-final` pushed, repo forked + rebranded |
| 1 — Security hardening | `phase-1-security.md` | ◐ 1.6/1.7/1.8 ✅ 2026-07-05 (DM1–DM3) — next: 1.1 |
| 2 — Deployability | `phase-2-deploy.md` | ☐ |
| FE — Frontend rebuild | `phase-fe-frontend.md` | ☐ before Phase 3 UI work |
| 3 — Self-service | `phase-3-selfservice.md` | ☐ |
| 4 — Reliability | `phase-4-reliability.md` | ☐ |
| 5 — Differentiators | `phase-5-differentiators.md` | ◐ 5.5 ✅ 2026-07-05 (pulled forward as DM4) |

Order: **1.6 → Phase 1 → 2 → FE → 3 → 4 → 5.** Sizes: S ≤1 day, M 2–4 days, L 1–2 weeks.

**Demo-minimal milestone (2026-07-05, `specs/spec-demo-minimal.md`)**: an alternative early sequence (DM1–DM9 ≈ tasks 1.6, 1.7, 1.8, 5.5, 4.1♻-scope, 3.1-partial, FE-minimal 5 screens, memoria quality prompts, eval-lite) that produces a **demo-safe build** (demo path fully rewritten, old SPA deleted) months before the selling gate — enables Phase-B personalized demos. Selling gate unchanged. Memoria quality prompts: `specs/spec-memoria-prompts.md`.

Costs (revised 2026-07-04): dedicated env ≈ €100–150/month fixed (AI Search Basic ~€70 dominates) + OpenAI/DI usage; standard tier ≈ €20–40/month marginal per client on the shared env. Price by tier value, not by cost.

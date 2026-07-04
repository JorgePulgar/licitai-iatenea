# Phase 1 — Security hardening

> Prereq reading: `plan/00-CONTEXT.md` (esp. §2 rewrite rules for ♻ tasks and §3 findings).
> Execution order inside the phase: **1.6 first** (live unauthenticated endpoint), then any order.

## 1.6 ♻ Rewrite `endpoints/audit.py` — URGENT — S — Opus 4.8

`GET /api/v1/system/audit` currently has **no auth dependency**: anyone reaching the API gets every user's email, full name, per-user usage and token counts (finding #2).

Rewrite from spec (do not edit the old file):
- Require `get_current_user` + `admin` role (403 for non-admin).
- Move response schemas to `models/schemas.py` (old file defines them inline).
- Kill the N+1: per-user activity currently runs 3 queries per user; use grouped aggregate queries.
- Keep it minimal — the full analytics dashboard comes in 5.2.

**Acceptance:** unauthenticated → 401; authenticated non-admin → 403; admin gets stats; tests for all three.

## 1.1 ♻ Blob SAS redesign — M — Fable 5

Finding #1: backend hands the browser a **container-level SAS** (`frontend/src/services/blobStorage.ts` + SAS endpoint in `endpoints/licitaciones.py`) — any logged-in user can read/write/delete any blob, including other users' pliegos.

- Design choice: per-blob or per-prefix (`{licitacion_id}/`) SAS, write-only, ≤15 min TTL — or proxy uploads through the backend entirely. Spec first, then implement.
- ♻ scope: full rewrite of `services/ingestion.py` and the upload/SAS paths of `endpoints/licitaciones.py` while here (co-authored file).
- Frontend upload client changes land in Phase FE; if FE not started yet, patch the existing `blobStorage.ts` minimally to match the new SAS shape.

**Acceptance:** integration test proves user A's SAS cannot read or write user B's path.

## 1.7 ♻ Rewrite `endpoints/query.py` — M — Opus 4.8

Defects found in the old file:
- `except Exception` swallows persistence failures silently (no logging).
- **Never persists `tokens_prompt` / `tokens_completion` / `latency_ms`** — columns exist, always NULL. Usage reporting (5.4) depends on these.
- Sessions listing does an N+1 (extra query per session for the first question) — use a window function or single grouped query.
- History endpoint unpaginated.

Keep behavior: session-scoped chat memory (`HISTORY_TURNS=6`), legacy NULL-session fallback, ownership check helper. **Acceptance:** telemetry columns populated on every query; no silent excepts; sessions endpoint = 2 queries max; paginated history; tests.

## 1.2 Rate limiting — S — Sonnet 5

`slowapi`. Login 5/min/IP; `/query` 20/min/user; uploads 10/hour/user; sensible default for the rest. **Acceptance:** 429 beyond limits; test covers login.

## 1.3 ♻ Security headers — S — Sonnet 5

Middleware: HSTS, CSP (script-src 'self'; mitigates finding #4 until Phase FE), X-Content-Type-Options, X-Frame-Options. ♻ scope: rewrite `app/main.py` (co-authored) while adding it — router mounting, middleware, lifespan, same behavior. **Acceptance:** headers on all responses.

## 1.4 ♻ Managed Identity + config factory — M — Fable 5

Finding #5: all Azure services use key auth from KV secrets.
- `DefaultAzureCredential` for Search, Storage, OpenAI (`azure-identity` token provider), Document Intelligence; keys remain as dev fallback.
- ♻ rewrite `core/config.py`: no import-time mutation (`settings.load_from_keyvault()` at import), use a settings factory / dependency; testable without Azure.
- ♻ rewrite `services/embeddings.py` with the new client wiring + tenacity retry/backoff.

**Acceptance:** prod path runs with zero keys in KV except JWT-SECRET and SQL-CONNECTION; unit tests construct settings without KV.

## 1.5 Filter input validation — S — Haiku 4.5

UUID-regex validation before interpolating IDs into OData filter strings (`services/indexing.py` delete filter, `services/query.py` search filters). Malformed → 400. **Acceptance:** test with `x' or pliego_id ne '` style input rejected.

---

Done when: all 7 tasks merged, findings #1 #2 #3 #5 closed, inventory rows for `audit.py`, `query.py`, `ingestion.py`, `main.py`, `config.py`, `embeddings.py`, `licitaciones.py` (partial — 3.1 finishes it) ticked in `00-CONTEXT.md`.

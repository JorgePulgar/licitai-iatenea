# Phase 3 — Self-service product (org model + user lifecycle)

> Prereq reading: `plan/00-CONTEXT.md` §2 (rewrite rules). Phase FE should be done (3.5 builds on the new frontend).
> **Status:** DM6 ✅ 2026-07-16 (partial 3.1: `endpoints/perfil.py` rewritten ♻, single-profile user-scoped, NO org model/migration — schema untouched). Done tasks get ✅ on their heading here; canonical status lives in `00-CONTEXT.md` §5 (phase table) + §2 (inventory) + the DM table in `specs/spec-demo-minimal.md`. 3.1 here remains open; only the perfil rewrite is done (it becomes org-scoped multi-profile when 3.1 lands).

## 3.1 ♻ Organization model — L — Fable 5

Highest regression risk in the plan: isolation touches every query.

- New `organizations` table; `users.org_id`; `org_id` on `licitaciones`, `company_profiles`, `company_templates`. Roles: `admin` | `member` (on `users.role`).
- All DB queries switch isolation from `user_id` to `org_id`. AI Search: add `org_id` filterable field, include in every search filter, reindex existing data (pattern: `scripts/reindex_pliegos.py`).
- Alembic migration (2.4 must be done).
- ♻ scope — full rewrites: `models/domain.py`, `models/schemas.py`, `endpoints/perfil.py` (org-scoped company profile; fix single-profile `first()` hack, support multiple named profiles with one default), `services/indexing.py` (org field + the batching logic re-specced), remaining co-authored parts of `endpoints/licitaciones.py`.

**Acceptance:** two users of the same org see the same licitaciones; member cannot manage users; cross-org isolation test (org A never sees org B in DB or Search results); reindex script run documented.

## 3.2a Email service — M — Sonnet 5

Azure Communication Services (add to Bicep). Templates: invite, password reset, deadline alert. Sender per client env. **Acceptance:** test email delivered from a client env.

## 3.2b ♻ Rewrite templates feature — M — Opus 4.8

Replaces `services/templates.py`, `endpoints/templates.py`, `prompts/templates.py`. Improvements over the old implementation (spec these in):
- Async Azure clients — old code calls sync DI/Blob inside `async def`, blocking the event loop.
- Reuse `ocr.py` extraction instead of duplicating DI parsing (DRY).
- Retry/backoff on Azure calls (tenacity, per project conventions).
- File-size cap on uploads (e.g. 25 MB) + MIME sniffing, not just declared type.
- **Org-wide sharing** (templates belong to the org, not the user — needs 3.1).
- `POST /templates/{id}/regenerate-summary` endpoint (old code had no retry path when summary generation failed).

**Acceptance:** upload PDF+DOCX, summary generated, org-mates see it; event loop not blocked (async test); size cap enforced.

## 3.3 Invite flow — M — Opus 4.8

Admin invites by email → tokenized link (signed, 72h) → user sets password. Removes the disabled-registration problem. **Acceptance:** end-to-end invite without dev intervention; token single-use.

## 3.4 Password reset — S — Opus 4.8

Tokenized email link, 1h expiry, single-use, no user enumeration in responses. **Acceptance:** reset works; used/expired token rejected.

## 3.5 Admin settings UI — M — Sonnet 5

In the new frontend: user list, invite, deactivate, role change (org admin only). **Acceptance:** admin manages users without touching the DB.

## 3.6 Deadline alerts — M — Sonnet 5

Daily job (Container Apps job or scheduler) emails upcoming `licitaciones.deadline` at 7/3/1 days, org-scoped, opt-out flag per user. **Acceptance:** alerts fire on schedule against seeded data.

---

Done when: a client org onboards (admin created via 2.5 CLI → invites team → shared workspace) with zero manual DB work; inventory rows for 3.1/3.2b files ticked.

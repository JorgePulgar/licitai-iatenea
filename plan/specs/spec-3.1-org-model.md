# Spec 3.1 — Organization model

> Fable-written spec, 2026-07-02. Implementer: Opus 4.8. Review: checklist at end. Prereq: Alembic (2.4).
> ♻ Full rewrites: `models/domain.py`, `models/schemas.py`, `endpoints/perfil.py`, `services/indexing.py`, remaining co-authored parts of `endpoints/licitaciones.py`.
> Highest regression risk in the plan: isolation moves from user to org. Schema change — confirm migration with Jorge before applying.

## 1. Model

```
organizations: id (str36 pk), name (nvarchar 255), created_at, is_active (bool default 1)
users:        + org_id (str36, FK organizations.id, NOT NULL after backfill), role stays ('admin'|'member')
licitaciones: + org_id (str36, indexed, NOT NULL after backfill)   -- user_id KEPT as "created_by" semantics
company_profiles:  created_by kept; + org_id (indexed, NOT NULL)   -- profiles belong to org; multiple named, one is_default per org
company_templates: user_id kept as creator; + org_id (indexed, NOT NULL)
```

Children of licitaciones (`pliegos`, `queries`, `memoria_*`, `pliego_requirements`, `match_results`, `licitacion_summaries`) do **not** get org_id — they inherit isolation through their licitación join. `queries.user_id`, `memoria_*.user_id` stay for attribution.

**Chat/session privacy decision**: query history and memoria chat stay **per-user within the org** (a user's chat threads are theirs); licitaciones, documents, summaries, requirements, match results, templates, profiles are **org-shared**. Rationale: shared workspace for the bid, private conversations.

## 2. Isolation rule (the one invariant)

> Every read/write of an org-shared resource filters by `org_id == current_user.org_id`. Every read of a private resource filters by `user_id == current_user.id` AND reaches the licitación through an org check. **No endpoint may filter by user_id alone for org-shared data.**

New dependency in `core/deps.py`:
```python
def get_current_org(current_user = Depends(get_current_user)) -> str:  # returns org_id, 403 if user has none
```

## 3. Migration order (Alembic, one revision per step)

1. Create `organizations`; insert default org `"Default"` (per-client env = usually one org).
2. Add nullable `org_id` to users/licitaciones/company_profiles/company_templates.
3. Backfill: all existing rows → default org id.
4. Alter to NOT NULL + indexes + FKs.
5. AI Search: add `org_id` (Edm.String, filterable) to the index definition (additive, `create_or_update_index`); run reindex script (pattern: `scripts/reindex_pliegos.py`) to populate; chunks without org_id remain reachable until reindexed — **gate: reindex completes before deploying the filter switch** (or deploy filter as `org_id eq X or licitacion_id in (org's ids)` interim; simpler: reindex first, then deploy — per-client envs are small).

## 4. Change matrix (complete — the regression-risk part)

| Location | Current filter | New filter |
|---|---|---|
| `endpoints/licitaciones.py` list/get/patch/delete | `Licitacion.user_id == user.id` | `Licitacion.org_id == org_id` |
| upload-urls + create (spec 1.1) | user-owned | org-owned; `user_id` recorded as creator |
| summary / match / requirements endpoints (ownership checks) | via licitación user_id | via licitación org_id |
| `endpoints/query.py` POST (licitación check) | user_id | org_id (licitación) — but history/session queries keep `Query.user_id == user.id` (private chats) |
| `endpoints/query.py` sessions/history | user_id | unchanged (private) + licitación org check |
| `endpoints/perfil.py` | `created_by == user.id`, single profile | org-scoped: list profiles, CRUD (admin-only for delete), one `is_default` per org enforced in code |
| `endpoints/templates.py` + `services/templates.py` | `user_id` | `org_id` (shared); creator recorded |
| `endpoints/memoria.py` (esquema/propuesta/chat/export) | user_id per resource | licitación org check; chat messages stay per-user |
| `endpoints/audit.py` (rewritten in 1.6) | global | org-scoped (admin sees own org only) |
| `services/query.py` `hybrid_search` filter string | `licitacion_id eq X and user_id eq Y` | `licitacion_id eq X and org_id eq Y` |
| neighbor expansion filter (same file) | same | same switch |
| `services/indexing.py` chunk docs + delete filters | user_id field | + org_id field populated; delete filter unchanged (pliego_id) |
| `services/requirements.py` (5.5 rewrite) | hybrid_search(user_id) | hybrid_search(org_id) |
| `auth.py DELETE /me` (RGPD) | deletes user's licitaciones | **changes meaning**: deletes user account + their private chats; org-shared data stays unless user is the org's last member → then full org purge. Document in the endpoint. |
| `core/deps.py` | get_current_user | + get_current_org |
| retention job | per-pliego | unchanged (org-agnostic) |
| `scripts/seed_users.py` / 2.5 CLI | creates user | creates org + admin user |

JWT: add `org` claim optionally, but **authoritative org comes from the DB row** (`user.org_id`) — never trust the token's org for filtering (stale after user moves org).

## 5. Roles

- `admin`: manage users (Phase 3.3/3.5), delete org resources (profiles, templates, licitaciones of others), see org audit (1.6/5.2).
- `member`: everything else. Deleting a licitación you didn't create: admin-only (409 for members — PO-style decision, confirm with Jorge if 403 preferred).
- Dependency: `require_admin` in `core/deps.py`.

## 6. Tests (acceptance)

1. Two users, same org: both see the same licitaciones list, same templates, same profiles.
2. Two orgs (A, B): every list endpoint returns zero cross-org rows; direct GET by id of B's resource from A → 404.
3. AI Search isolation: query against A's licitación with B's user → no chunks (filter test with mocked/real search).
4. Chat privacy: user1 and user2 in same org, same licitación — sessions lists are disjoint.
5. member cannot invite/deactivate/change roles (403); admin can.
6. `is_default` uniqueness per org enforced.
7. RGPD delete: non-last member → org data intact, their chats gone; last member → full purge (blobs+index+db).
8. Migration test: run against a copy with existing data → all rows in default org, NOT NULL holds.

## 7. Opus review checklist

- [ ] Grep proves no org-shared resource query filters by `user_id` alone (`rg "user_id ==" backend/app` reviewed line-by-line against §4 matrix).
- [ ] Search filter string uses org_id; neighbor expansion too; filter built via the validated-UUID helper (task 1.5).
- [ ] org_id never taken from JWT/request body — always `current_user.org_id` from DB.
- [ ] Migration is 4 separate steps (create/add-nullable/backfill/not-null) — no single-shot NOT NULL add.
- [ ] Index change is additive; reindex script updated and its run documented in the deploy notes.
- [ ] RGPD delete semantics implemented and documented as §4 describes.
- [ ] All 8 acceptance tests present; cross-org test covers EVERY router, not just licitaciones.
- [ ] `models/domain.py` + `schemas.py` are rewrites (new organization, not the old file with columns bolted on).

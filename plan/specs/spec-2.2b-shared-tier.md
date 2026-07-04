# Spec 2.2b — Two-tier infrastructure (shared standard tier)

> Fable-written addendum, 2026-07-04. Amends spec-2.2 (Bicep), spec-3.1 (org model), tasks 2.5/2.6. Implementer: Opus 4.8. Review checklist at end.
> Context: business model changed 2026-07-04 (see `plan/00-CONTEXT.md` §1) — **standard tier** = all standard clients on ONE shared Azure environment; **dedicated tier** = spec-2.2 per-client env, unchanged, now the premium SKU.

## 1. What is shared vs per-client (the decision)

| Layer | Standard (shared env) | Rationale |
|---|---|---|
| SQL | ONE database, isolation via `org_id` filtering (spec-3.1, already the tested invariant) | Rows are metadata; filter discipline + spec-3.1's cross-org test suite covers it. Schema-per-client rejected: SQLAlchemy multi-schema routing pain > benefit |
| AI Search | ONE service, **one index per client org** (physical isolation) | The corpus is the sensitive asset. Index-per-org means a filter bug cannot leak chunks across clients; offboarding = delete index |
| Blob | ONE account, **one container per client org** | Same logic; SAS scoping (spec-1.1) stays per-blob within the org's container |
| Queues | Shared `jobs`/`jobs-poison`; messages carry `org_id` | Worker resolves tenant context per message (§3) |
| OpenAI / DI | Shared accounts | Usage metered per org (§5) |
| Backend/Worker/SWA | One deployment serves all standard clients | The whole point of the tier |

Defense-in-depth: the `org_id` filterable field from spec-3.1 §3.5 **stays in every index** even though indexes are per-org — belt and braces, and it keeps query code identical across tiers.

**Tier equivalence invariant**: a dedicated env is exactly a shared env with one tenant. Same code, same schema, same per-org index/container naming. No `if tier == ...` branches in application logic — the org row (§2) is the only source of routing truth.

## 2. Tenant registry (extends spec-3.1 `organizations`)

```
organizations: + search_endpoint   (nvarchar 255)  -- which Search service (supports >1 shared service later, §6)
               + search_index      (nvarchar 128)  -- e.g. "org-<id>"
               + storage_container (nvarchar 63)   -- e.g. "org-<id>" (container naming rules: lowercase, 3–63)
               + tier              ('standard'|'dedicated')
               + monthly_token_quota (int, nullable = unlimited)
```

- Names derived from org id, not client name (rename-safe, charset-safe).
- `services/indexing.py`, `services/query.py` (hybrid_search + neighbor expansion), pipeline, and SAS issuance resolve index/container **from the caller's org row** — never from env config. Config (spec-1.4) keeps only service endpoints/credentials; per-tenant names move to the DB.
- JWT still carries nothing authoritative (spec-3.1 §4 rule unchanged).

## 3. Provisioning flow (replaces "Bicep creates everything" for standard tier)

- **Bicep** (spec-2.2 modules reused) gains param `envType: 'shared' | 'dedicated'`:
  - `shared`: provisions the env WITHOUT any index/container (those are per-tenant, created at onboarding); tags `client=shared`; bigger `budgetEur`.
  - `dedicated`: unchanged spec-2.2 behavior + the admin CLI still creates the tenant row (single org).
- **Admin CLI (task 2.5) extension**:
  `python -m app.cli create-tenant --name acme --tier standard [--quota N]` →
  1. create org row + derived names; 2. create Search index (same definition as spec-1.x index, via `create_or_update_index`); 3. create blob container; 4. create org admin user (existing 2.5 flow); 5. print onboarding summary.
  `delete-tenant --org <id> --confirm` → offboarding: delete index, delete container (soft-delete window applies), purge org rows (spec-3.1 RGPD purge order), write audit record. **This command is the offboarding protocol's technical half.**
- Worker: reads `org_id` from queue message → loads org row → same resolution path as the API.

## 4. Capacity limits & scale triggers (shared Search service)

- AI Search Basic: **15 indexes max**; storage per partition ~15 GB on services created after Apr 2024 (older services 2 GB) — **verify limits at implementation time**, they move.
- Scale triggers (document in runbook, alert on them):
  - **≥12 indexes** on one service → provision second shared Search service (Bicep re-run, `shared-2`); new tenants get the new `search_endpoint`. The registry (§2) already supports this — zero code change.
  - Storage pressure on a partition → same response, or move the biggest tenant to dedicated (§7).
- SQL S0 and ACA sizing revisited at ~10 active tenants (observability data decides, task 4.2).

## 5. Per-tenant metering & cost guardrails (amends task 2.6)

- Shared env budget is RG-scoped (whole env) — per-client attribution is **app-level**:
  `usage_daily: org_id, date, tokens_in, tokens_out, di_pages, queries, uploads` (upserted by the services that call OpenAI/DI; the audit rewrite 1.6/5.2 reads from this too).
- `monthly_token_quota` enforced in the OpenAI-calling path: over quota → 429 with clear message (ties into rate limiting task 1.2). Default quota for standard tier set at onboarding; dedicated default = unlimited.
- Weekly job (or on-demand CLI `usage-report`) → per-org usage summary; this is the billing-sanity + "uncapped LLM bill" guard for the shared env.

## 6. What does NOT change

- spec-1.1 (SAS): unchanged — SAS already per-blob; container now comes from org row.
- spec-1.4 (Managed Identity): unchanged — same MI accesses all tenant indexes/containers (RBAC is service-scoped).
- spec-3.1: all filters, migration order, tests unchanged; §2 columns are additive (one extra Alembic revision after 3.1's).
- spec-4.1 (queue): message schema gains `org_id`; everything else unchanged.
- Dedicated tier: spec-2.2 as written.

## 7. Tier migration runbook (standard → dedicated)

1. Provision dedicated env (spec-2.2, `envType: dedicated`, client params).
2. `azcopy` org container → new env's container.
3. Re-run indexing pipeline from blobs in the new env (index rebuild beats index copy — same pipeline, guaranteed-consistent) OR for large tenants: export/import index JSON.
4. SQL: export org's rows (script `scripts/export_tenant.py` — all tables in spec-3.1's model, ordered parent→child) → import into dedicated DB.
5. Smoke: counts match (licitaciones, pliegos, chunks per index), one known query returns identical citations.
6. `delete-tenant` on the shared env. Client's URL switches via SWA/custom domain.

Downgrade (dedicated → standard) = same steps reversed. Document both in `infra/README.md`.

## 8. Acceptance

1. Shared env up via Bicep (`envType=shared`); `create-tenant` × 2 → two orgs, two indexes, two containers, zero portal steps.
2. Full spec-3.1 cross-org test suite passes with the two tenants on the shared env (including search isolation — now doubly enforced).
3. Upload + pipeline + query for tenant A lands only in A's index/container (assert index name in search calls, container in blob calls).
4. Quota: set tenant A quota to tiny value → 429 on exceed; tenant B unaffected.
5. `delete-tenant` A → index gone, container gone, rows purged; tenant B fully functional.
6. Migration runbook executed once against a test tenant → counts + citation smoke pass.
7. Dedicated env provisioned from the same codebase serves its single tenant identically (tier equivalence invariant).

## 9. Opus review checklist

- [ ] No `if tier` branches in app logic — routing only via org row fields.
- [ ] Index/container names derived from org id with charset/length guards (container 3–63 lowercase; index name rules).
- [ ] Every Search/Blob call site resolves names from the org row — grep for hardcoded index/container config and remove (`rg "SEARCH_INDEX|CONTAINER_NAME" backend/app`).
- [ ] `org_id` filter retained in queries despite per-org indexes (defense-in-depth).
- [ ] `delete-tenant` purge order matches spec-3.1 RGPD order (blobs → index → DB) and is idempotent on re-run.
- [ ] Quota check wraps ALL OpenAI-calling paths (query, summary, match, requirements, memoria, templates) — not just chat.
- [ ] `usage_daily` writes are best-effort (metering failure must never fail a user request).
- [ ] Bicep `envType=shared` provisions no tenant resources; `dedicated` path unchanged vs spec-2.2 (what-if diff reviewed).
- [ ] Acceptance 1–7 all present as tests/runbook entries.

# Spec 2.2 — Bicep per-client environment

> Fable-written architecture, 2026-07-02. Implementer: Opus 4.8. Review checklist at end.
> Goal: `az deployment sub create -f infra/bicep/main.bicep -p clients/<name>.bicepparam` → complete client env, zero portal steps.
> **AMENDED 2026-07-04 by `spec-2.2b-shared-tier.md`** (two-tier model): this spec describes the dedicated tier; the shared standard tier adds an `envType` param and moves index/container creation to the admin CLI. Read both before implementing.

## 1. Layout

```
infra/bicep/
├── main.bicep              # subscription scope: RG + module calls
├── modules/
│   ├── data.bicep          # SQL server+db, storage(+queues), search
│   ├── ai.bicep            # OpenAI (+deployments), document intelligence
│   ├── apps.bicep          # ACA env, backend app, worker app, SWA
│   ├── observability.bicep # log analytics, app insights, alerts (4.2 adds rules)
│   ├── keyvault.bicep
│   └── rbac.bicep          # all role assignments in one reviewable place
└── clients/
    └── <client>.bicepparam # name, location pair, sku overrides, budget, alert email
```

## 2. Naming & tagging

- Names: `<res>-licitai-<client>-<loc>` (e.g. `srch-licitai-acme-swc`); storage: `stlicitai<client>` (24-char guard).
- Tags on RG + every resource: `product=licitai`, `client=<name>`, `managedBy=bicep`. Budget (2.6) keys off the RG.

## 3. Resources & SKUs

| Resource | SKU / config |
|---|---|
| Resource group | location = `spaincentral` (fallback `swedencentral`) |
| Azure SQL | server (AAD admin = Jorge's identity/group) + DB S0; v1: `Allow Azure services` ON (ACA consumption egress IPs are NOT static — per-IP firewall rules would break randomly); later hardening: VNet integration + private endpoint |
| Storage | StorageV2, LRS, soft-delete 14d + versioning; container `pliegos-raw`; queues `jobs`, `jobs-poison` (spec 4.1); public blob access disabled; CORS for SWA origin (browser PUT with SAS, spec 1.1) |
| AI Search | Basic, 1 replica/partition; `authOptions: aadOrApiKey` |
| Azure OpenAI | S0. Deployments (names = params, defaults): `chat` (gpt-4o-mini or per-client), `chat-heavy` (gpt-4o, memoria), `embeddings` (text-embedding-3-small). **Region param decides data residency — Spain Central if models available, else Sweden Central; document choice per client** |
| Document Intelligence | S0 |
| Key Vault | RBAC mode; secrets: JWT-SECRET (generated at provision via deployment script or set post-deploy by runbook), SQL-CONNECTION |
| Log Analytics + App Insights | workspace-based, 30d retention |
| ACA environment | consumption; zone redundancy off (cost) |
| Backend app | 0.5 vCPU/1Gi, min 1 replica (cold start hurts UX), system-assigned MI, ingress external :8000, health probe `/health`; secrets via KV reference; APPINSIGHTS via env |
| Worker app | same image, entrypoint `python -m app.worker`, min 0/max 2, KEDA azure-queue scaler (queueLength 1), terminationGracePeriod 300s, same MI or its own |
| Static Web App | Free/Standard; custom domain later; SPA fallback to index.html; env var with API URL |
| Budget | RG-scoped, amount param, alert at 80/100% → email param (2.6) |

## 4. RBAC (module `rbac.bicep`) — from spec-1.4 §3

Backend MI + Worker MI each get: Search Index Data Contributor + Search Service Contributor; Storage Blob Data Contributor + Storage Blob Delegator + Storage Queue Data Contributor; Cognitive Services OpenAI User; Cognitive Services User (DI); Key Vault Secrets User.
SQL contained-user creation is a documented runbook step (cannot be done in Bicep).

## 5. Parameters (per client `.bicepparam`)

`clientName`, `location`, `sqlSku`, `searchSku`, `openAiRegion`, `chatModel`+`version`, `heavyModel`, `budgetEur`, `alertEmail`, `swaLocation`, `corsOrigins`, `jwtSecretValue` (secure, optional — else runbook sets it).

## 6. Ordering/dependency notes for the implementer

- OpenAI model deployments need `dependsOn` chaining (serial) — parallel deployment of multiple model deployments on one account fails.
- Search service name must be globally unique lowercase; add `uniqueString(rg.id)` suffix option.
- KV purge protection ON (client data env) — document that re-provision with same name needs purge or new name.
- ACA app needs the image to exist → first deploy uses a public placeholder image param; CI (2.3) then deploys the real image. Document the two-step bootstrap in the runbook.
- Outputs: backend FQDN, SWA URL, search/openai endpoints, storage account name, MI principal IDs — CI consumes these.

## 7. Acceptance

1. Fresh subscription (or clean RG scope): one command → all resources green.
2. `curl https://<backend-fqdn>/health` → ok after CI deploys image.
3. MI smoke: backend can list the container, query search, call OpenAI (script `infra/smoke.sh` doing the three calls via the app's debug endpoint or a one-off job).
4. Second client param file → second env, zero collisions.
5. `what-if` on re-run → no changes (idempotent).

## 8. Opus review checklist

- [ ] No secrets in bicep/params committed (JWT param secure + optional; no keys output).
- [ ] Every resource tagged; names within Azure length/charset limits (storage 24, kv 24).
- [ ] RBAC matches spec-1.4 §3 exactly; nothing broader (no Contributor-on-RG shortcuts).
- [ ] Public blob access disabled; SQL firewall not 0.0.0.0-open; Search/OpenAI local auth per spec.
- [ ] Queues present for 4.1; CORS on storage matches SWA origin param.
- [ ] Bootstrap ordering documented (placeholder image, SQL contained user, JWT secret) in `infra/README.md`.
- [ ] `what-if` idempotence verified in acceptance run.

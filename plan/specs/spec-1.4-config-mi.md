# Spec 1.4 — Managed Identity + settings factory

> Fable-written spec, 2026-07-02. Implementer: Opus 4.8 (acceptable) — review checklist at end.
> ♻ Full rewrites: `core/config.py`, `services/embeddings.py`.

## 1. Problems in the current code

- `core/config.py` mutates a module-level `Settings` instance at import (`settings.load_from_keyvault()` at the bottom) — untestable, import-order-sensitive, KV call on every import including tests/scripts.
- All Azure services authenticate with keys pulled from KV (SEARCH-ADMIN-KEY, STORAGE key, DOC-INTEL-KEY, OPENAI-KEY) → per-client key rotation burden, keys in memory/env.
- Client construction is scattered (each service builds its own client from `settings`).

## 2. Target design

### 2.1 Settings factory (`core/config.py` rewrite)

```python
class Settings(BaseSettings): ...          # pure declaration, NO methods with side effects
@lru_cache
def get_settings() -> Settings: ...        # loads .env; overlays KV only if KEY_VAULT_NAME set
```
- KV loading becomes a pure function `overlay_keyvault(settings) -> Settings` called inside `get_settings()`; tests call `Settings(...)` directly or override the FastAPI dependency.
- Keep the ADO→SQLAlchemy conversion and JWT dev-fallback logic (re-specced, reimplemented): fallback still refuses non-dev startup without JWT-SECRET.
- After MI adoption, KV holds only: `JWT-SECRET`, `SQL-CONNECTION`, `APPINSIGHTS-CONNECTION-STRING` (that one can move to app config, it's not secret-critical).

### 2.2 Credential + client factory (`core/azure_clients.py`, new)

```python
@lru_cache
def get_credential() -> TokenCredential   # DefaultAzureCredential (managed identity in ACA, az-cli locally)
def get_search_client() / get_search_index_client()
def get_blob_service_client()
def get_document_intelligence_client()
def get_openai_client()                   # AsyncAzureOpenAI with azure_ad_token_provider
```
- Rule: **MI-first, key-fallback**. If the corresponding key setting is present (dev), use key auth; else `get_credential()`. One place decides, services never touch credentials.
- OpenAI: `azure.identity.get_bearer_token_provider(credential, "https://cognitiveservices.azure.com/.default")`.
- SQL: keep current Azure AD token path via pyodbc attrs (already works); document it here as the pattern.
- SAS generation (spec 1.1): helper takes user-delegation key from `get_blob_service_client()` when running on MI, account key when on connection string — the parameterization point spec 1.1 §D3 references.

### 2.3 `services/embeddings.py` rewrite

- Uses `get_openai_client()`; batching (≤100/call) and tenacity retry (exponential, retry on 429/5xx/timeouts, max ~5 attempts) — behavior per claude.md §9.
- All other services migrate to the client factory in their own rewrite tasks; until then they keep working because key settings remain supported.

## 3. RBAC roles the Bicep must grant the backend/worker identity (input to 2.2)

| Service | Role |
|---|---|
| AI Search | Search Index Data Contributor + Search Service Contributor (index create) |
| Blob | Storage Blob Data Contributor + (for user-delegation SAS) Storage Blob Delegator |
| Queues (spec 4.1 worker/API) | Storage Queue Data Contributor |
| Azure OpenAI | Cognitive Services OpenAI User |
| Document Intelligence | Cognitive Services User |
| Key Vault | Key Vault Secrets User |
| SQL | Azure AD admin creates contained user for the identity (`CREATE USER [app] FROM EXTERNAL PROVIDER`) — runbook step, not Bicep |

Also required on the services: AI Search `authOptions: aadOrApiKey` (or aad only), OpenAI/DI `disableLocalAuth` optionally true later.

## 4. Tests (acceptance)

1. `Settings()` constructible in tests with no KV/network (no import side effects — assert importing `app.core.config` performs no KV call).
2. Client factory returns key-auth clients when key settings present, MI clients otherwise (assert credential type).
3. Embeddings retry: mock 429 twice → succeeds on 3rd; mock permanent 500 → raises after max attempts.
4. App boots with ONLY `JWT-SECRET` + `SQL-CONNECTION` secrets in a KV-less env config (dev fallback path).
5. Existing endpoints keep passing (clients injected the same way functionally).

## 5. Opus review checklist

- [ ] Zero side effects at import time in `config.py` (no module-level `load_*` call).
- [ ] `get_settings()` cached; FastAPI deps use it; tests shown overriding it.
- [ ] One credential decision point (`azure_clients.py`); no service constructs `AzureKeyCredential`/connection strings itself anymore (embeddings now; others noted as TODO tied to their rewrite tasks).
- [ ] JWT non-dev refusal preserved.
- [ ] Retry/backoff on embeddings per §2.3; no bare `except`.
- [ ] RBAC table copied into the Bicep spec/params (cross-check with spec-2.2).
- [ ] Tests 1–5 present; test 1 actually asserts no network call (mock KV SDK, assert not called).

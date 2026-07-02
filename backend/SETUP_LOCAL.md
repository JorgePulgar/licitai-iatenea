# LicitAI Backend — Local Setup Guide

> Single-source guide for getting a developer machine ready to work on the LicitAI backend.
> Read this end-to-end before starting a new coding session.

---

## 1. Overview

The backend is a **FastAPI** application that connects to:

- **Azure SQL Server** (relational DB, via SQLAlchemy + pyodbc).
- **Azure Blob Storage** (raw uploaded pliegos).
- **Azure Document Intelligence** (OCR `prebuilt-layout`).
- **Azure AI Search** (HNSW index + semantic ranker).
- **Azure OpenAI** (`gpt-4o-mini` for answers, `text-embedding-3-small` for embeddings).

All credentials live in **Azure Key Vault**. The backend pulls them on startup via `DefaultAzureCredential`. The only thing you keep in your local `.env` is the **name of the Key Vault** plus a couple of non-secret defaults.

---

## 2. Automated setup (recommended)

From the repository root, on macOS, Debian/Ubuntu Linux, or Windows with WSL2:

```bash
./dev.sh
```

The bootstrap creates `backend/.venv` with Python 3.11+, installs
`requirements.txt` and `requirements-dev.txt`, installs frontend packages,
checks WeasyPrint/Pango and ODBC Driver 18, requests Azure authentication, and
applies additive database setup scripts.

To prepare a new computer without starting FastAPI and Vite:

```bash
BOOTSTRAP_ONLY=1 ./dev.sh
```

Useful overrides:

```bash
SKIP_SYSTEM_DEPS=1 ./dev.sh   # system packages are already managed externally
SKIP_AZURE_LOGIN=1 ./dev.sh   # skip the interactive Azure login check
SKIP_DB_SETUP=1 ./dev.sh      # skip shared database setup
SKIP_BOOTSTRAP=1 ./dev.sh     # start using an already prepared environment
BACKEND_PORT=8100 FRONTEND_PORT=5174 ./dev.sh  # use alternate ports
```

The remaining sections document the equivalent manual setup and Azure access
requirements.

---

## 3. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11+ | Backend runtime |
| Azure CLI | latest | `az login` to authenticate against the Key Vault |
| ODBC Driver 18 for SQL Server | latest | Required by `pyodbc` to talk to Azure SQL |
| Pango | latest | Required by WeasyPrint to export Memoria PDFs |
| Node.js | 18+ | Frontend runtime |
| Git | any | Version control |
| (Optional) VS Code | latest | Recommended IDE with Python + Pylance extensions |

### Install ODBC Driver 18 (Windows)

1. Download the MSI from Microsoft: *ODBC Driver 18 for SQL Server*.
2. Install it with default options.
3. Verify: open PowerShell and run `Get-OdbcDriver | Where-Object {$_.Name -like "*18*"}`. It must list `ODBC Driver 18 for SQL Server`.

### Install Azure CLI (Windows)

1. Download the MSI from Microsoft: *Azure CLI*.
2. After install, run `az --version` in a fresh PowerShell. It must print a version.

### Install Pango / GTK native libs (Windows)

WeasyPrint needs the GTK native libraries (Pango, GLib, cairo). On Linux these
come from the system package manager; on Windows install them via MSYS2:

1. Install MSYS2:
   ```powershell
   winget install --id MSYS2.MSYS2 -e
   ```
2. Install pango (pulls glib/cairo/harfbuzz as deps):
   ```powershell
   & C:\msys64\usr\bin\pacman.exe -Sy --noconfirm
   & C:\msys64\usr\bin\pacman.exe -S --noconfirm mingw-w64-x86_64-pango
   ```
3. Verify (no PATH change needed — WeasyPrint 69+ auto-loads from
   `C:\msys64\mingw64\bin`):
   ```powershell
   & .\.venv\Scripts\python.exe -c "from weasyprint import HTML; print(HTML(string='<h1>ok</h1>').write_pdf()[:5])"
   ```
   It must print `b'%PDF-'`. If MSYS2 is installed elsewhere, point WeasyPrint at
   the libs with the env var `WEASYPRINT_DLL_DIRECTORIES=<path>\mingw64\bin`.

---

## 4. Azure access (do this once)

1. **Authenticate** with the Azure account that has access to the LicitAI Key Vault:
   ```powershell
   az login
   ```
   A browser opens. Pick the account that has rights on the LicitAI subscription.

2. **Verify Key Vault access**. Ask Álvaro to assign you the role *Key Vault Secrets User* on the Key Vault. Then test:
   ```powershell
   az keyvault secret show --vault-name <KV_NAME> --name OPENAI-ENDPOINT --query value -o tsv
   ```
   It should print the endpoint URL. If you get a `Forbidden`, your account does not have the role yet.

3. **Azure SQL firewall.** Your public IP must be allowlisted on the SQL server (`licitaiserver.database.windows.net`). Álvaro handles this — confirm with him when you change network (home/office/VPN).

---

## 5. Clone the repo and create the virtual environment

```powershell
git clone <repo-url> licitai
cd licitai\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

> If `pip install` fails on `pyodbc`, it almost always means ODBC Driver 18 is not installed (see section 2).

---

## 6. Create your `.env` file

Create `backend/.env` with the following content. **None of these values are secrets** — only pointers and toggles. All real secrets are pulled from Key Vault at runtime.

```dotenv
# Key Vault — name of the resource (NOT the URL)
KEY_VAULT_NAME=kv-licitai-dev

# Non-secret defaults
AZURE_STORAGE_CONTAINER_NAME=pliegos-raw
AZURE_SEARCH_INDEX_NAME=licitai-pliegos-index

# AI Search endpoint is a public URL, not a secret — keep it here
AZURE_SEARCH_ENDPOINT=https://<search-service-name>.search.windows.net

# Environment flag (controls dev-only endpoints like /auth/register)
ENVIRONMENT=dev
```

> Replace `<search-service-name>` with the real Azure AI Search resource name (ask Álvaro).
>
> The `.env` file is gitignored. Never commit it.

### What lives in Key Vault

These secrets are loaded by `app/core/config.py` on startup:

| Secret name in KV | Maps to Settings attribute |
|---|---|
| `SQL-CONNECTION` | `DATABASE_URL` |
| `STORAGE-CONNECTION-STRING` | `AZURE_STORAGE_CONNECTION_STRING` |
| `DOC-INT-ENDPOINT` | `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` |
| `DOC-INTEL-KEY` | `AZURE_DOCUMENT_INTELLIGENCE_KEY` |
| `OPENAI-ENDPOINT` | `AZURE_OPENAI_ENDPOINT` |
| `OPENAI-KEY` | `AZURE_OPENAI_KEY` |
| `SEARCH-ADMIN-KEY` | `AZURE_SEARCH_KEY` |
| `JWT-SECRET` *(pending — Álvaro, LIC-096)* | `JWT_SECRET` |

> `AZURE_SEARCH_ENDPOINT` is a public URL (`https://<service>.search.windows.net`), not a secret, and lives in `.env` rather than Key Vault.
>
> `JWT-SECRET` is not yet provisioned. Until it exists, the backend should generate a dev-only random fallback on startup and log a warning. Do **not** ship to production without the real Key Vault secret.

---

## 7. Database setup (Azure SQL)

The Azure SQL database is shared across the team. You don't create it locally.

### Create tables / seed dev users

Schema is no longer managed with Alembic migrations. Tables are created
directly from the SQLAlchemy models via `Base.metadata.create_all`, which runs
inside the seed script. The first time on a fresh database:

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/seed_users.py
```

This creates any missing tables and seeds the default dev users. It is safe to
run repeatedly — existing users are skipped, and `create_all` only adds tables
that don't already exist (it never alters or drops existing ones).

> ⚠️ This is a **shared** database. `create_all` does **not** apply changes to
> existing tables — if a model changes, coordinate the schema update manually.
> To wipe and recreate from scratch in dev, use `python drop_tables.py`
> (guarded: dev-only + interactive confirmation), then re-run the seed script.

### Connection details (for reference)

- Server: `licitaiserver.database.windows.net`
- Database: `licitaiserver`
- Auth: SQL Authentication (username + password embedded in `SQL-CONNECTION`)
- Driver: `ODBC Driver 18 for SQL Server` (you installed it in section 2)

---

## 8. Run the backend

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Expected output on first run:
- A line saying the Key Vault secrets have been loaded (or warnings if any secret is missing).
- A line saying the AI Search index has been synced.
- Uvicorn listening on `http://127.0.0.1:8000`.

### Smoke test

In a second PowerShell:

```powershell
# Health check
curl http://127.0.0.1:8000/health

# OpenAPI docs (open in browser)
start http://127.0.0.1:8000/docs
```

`/health` must return `{"status":"ok","version":"1.0.0"}`.

---

## 9. Run the tests

```powershell
.\.venv\Scripts\Activate.ps1
pytest -q
```

Tests use mocks for all Azure dependencies, so they run offline. The integration test in `tests/integration/test_pipeline_real_data.py` requires Azure credentials and is skipped by default unless the environment is configured.

---

## 10. Project structure (where to look)

```
backend/
├── app/
│   ├── api/v1/endpoints/    # FastAPI routers (pliegos.py; auth.py — to be added in F02)
│   ├── core/                # config.py (Settings + Key Vault loader), logging, security
│   ├── db/                  # SQLAlchemy Base, session factory
│   ├── models/              # SQLAlchemy ORM (domain.py) + Pydantic schemas (schemas.py)
│   ├── services/            # Business logic: ingestion, ocr, embeddings, indexing, pipeline
│   ├── prompts/             # LLM system prompts (to be added in F05)
│   └── main.py              # FastAPI app entrypoint
├── alembic/                 # DB migrations
├── tests/
│   ├── api/                 # Endpoint tests
│   ├── services/            # Service-level tests
│   ├── fixtures/pliegos/    # Real test PDFs from PLACSP
│   └── integration/         # End-to-end pipeline tests (offline-safe)
└── requirements*.txt
```

---

## 11. Sprint 2 — what to work on

You are **Jorge**, owning the backend track. The full Sprint 2 plan is in `docs/backlog/sprint-2.md`. The agreed order of work is:

1. **F02 — Authentication** (start here):
   - `LIC-053` User model + bcrypt hashing
   - `LIC-054` Login / me / register endpoints (register is dev-only)
   - `LIC-055` JWT middleware (`get_current_user` dependency)
   - `LIC-056` Seed users script

2. **Refactor F03 endpoints** to consume `current_user` from the JWT middleware and remove the `CURRENT_USER_ID = "user_dev_123"` mock in `app/api/v1/endpoints/pliegos.py`.

3. **F05 — RAG Query**:
   - `LIC-030` Hybrid search in AI Search
   - `LIC-031` LLM answer generation with inline citations `[p. X]`
   - `LIC-032` End-to-end `query.py` service
   - `LIC-033` `POST /api/v1/query` endpoint

4. **F06 — Summary and match score**:
   - `LIC-034` `GET /pliegos/{id}/summary`
   - `LIC-035` `POST /pliegos/{id}/match`

### Decisions already locked in

| Topic | Decision |
|---|---|
| Database | Azure SQL Server via `pyodbc` + ODBC Driver 18 |
| `Pliego.user_id` | Plain `String`, no ForeignKey to `users.id` (filter-by-user_id pattern) |
| `/auth/register` | Exposed in dev only, gated by `ENVIRONMENT=dev` |
| Order of work | F02 first, then F03 cleanup, then F05, then F06 |

### What NOT to touch without asking

Per `CLAUDE.md` section 14:
- Database schema changes beyond what's strictly required.
- Auth/security primitives once they are merged and validated.
- Versioned system prompts.
- Azure infra (indexes, models, Key Vault contents).
- Folder structure.

---

## 12. What `config.py` still needs (do this first in the next session)

The current `app/core/config.py` only loads four secrets from Key Vault: `OPENAI-ENDPOINT`, `OPENAI-KEY`, `SEARCH-ENDPOINT`, `SEARCH-KEY` — and it uses the wrong names for some of them. Before any feature work starts, `Settings` and `load_from_keyvault()` must be brought up to date.

### 12.1. Missing `Settings` attributes

Add these fields to the `Settings` class (none of them exist yet):

```python
# Auth
JWT_SECRET: str | None = None
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRATION_HOURS: int = 24

# Environment flag (controls dev-only endpoints like /auth/register)
ENVIRONMENT: str = "dev"  # "dev" | "staging" | "prod"
```

### 12.2. Fix the `load_from_keyvault()` mapping

The current implementation reads the wrong secret names. Replace the body with calls that match the **actual** KV inventory:

| Settings attribute | Real secret name in KV |
|---|---|
| `AZURE_OPENAI_ENDPOINT` | `OPENAI-ENDPOINT` |
| `AZURE_OPENAI_KEY` | `OPENAI-KEY` |
| `AZURE_SEARCH_KEY` | `SEARCH-ADMIN-KEY` |
| `AZURE_STORAGE_CONNECTION_STRING` | `STORAGE-CONNECTION-STRING` |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` | `DOC-INT-ENDPOINT` |
| `AZURE_DOCUMENT_INTELLIGENCE_KEY` | `DOC-INTEL-KEY` |
| `DATABASE_URL` | `SQL-CONNECTION` |
| `JWT_SECRET` | `JWT-SECRET` *(may not exist yet — handle gracefully)* |

Current code wrongly tries to read `AZURE-OPENAI-ENDPOINT`, `AZURE-OPENAI-KEY`, `AZURE-SEARCH-ENDPOINT`, `AZURE-SEARCH-KEY`. Those names do **not** exist in the vault.

### 12.3. Default for `DATABASE_URL`

The current default is a hardcoded PostgreSQL URL. Either:

- Drop the default entirely and require it to come from KV (preferred — fail fast if KV is unreachable), or
- Set a placeholder that obviously needs replacing (`""`).

The Azure SQL URL retrieved from `SQL-CONNECTION` should already use the SQLAlchemy `mssql+pyodbc://...?driver=ODBC+Driver+18+for+SQL+Server` format. If it doesn't, transform it inside the `@field_validator("DATABASE_URL")` instead of inside the calling code.

### 12.4. JWT fallback for local dev

Until `JWT-SECRET` exists in KV, the loader should:

1. Attempt to read `JWT-SECRET` from KV.
2. On failure, generate a dev-only random secret (`secrets.token_urlsafe(32)`).
3. Log a `WARNING` saying a dev fallback is in use.
4. Raise on startup if `ENVIRONMENT != "dev"` and there is no secret.

### 12.5. Optional cleanup

- The hardcoded value `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: str | None = "https://di-licitai-dev.cognitiveservices.azure.com/"` should be `None` by default — the real value comes from KV.
- CORS origins should move out of `main.py` into `Settings` (`CORS_ORIGINS: list[str] = ["http://localhost:5173"]`).

### 12.6. Order of work to bootstrap F02

Once `config.py` is fixed:

1. Verify `uvicorn app.main:app --reload` boots cleanly against Azure SQL (`SELECT 1` via SQLAlchemy on health check is a good smoke test).
2. Move on to **LIC-053** (User model + bcrypt + Alembic migration for `users`).
3. Then **LIC-055** (JWT middleware and `get_current_user` dependency), so the rest of the endpoints can adopt it.
4. Then **LIC-054** (login / me / register) and **LIC-056** (seed script).
5. Refactor `app/api/v1/endpoints/pliegos.py` to drop `CURRENT_USER_ID = "user_dev_123"` and consume `current_user` from the JWT dependency.

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pip install` fails on `pyodbc` | ODBC Driver 18 missing | Install MSI (section 2) |
| `Login failed for user 'xxx'` on uvicorn startup | Wrong SQL credentials or IP not allowlisted | Re-check `SQL-CONNECTION` in KV; ask Álvaro to whitelist your IP |
| `DefaultAzureCredential failed to retrieve a token` | Not logged in to Azure | Run `az login` |
| `KeyVaultErrorException: Forbidden` | No KV role assigned | Ask Álvaro for *Key Vault Secrets User* role |
| Backend starts but `/health` works only intermittently | Token cache expired in middle of session | `az login` again; in prod this is solved by Managed Identity |
| `pyodbc.InterfaceError: Driver not found` | Driver installed but wrong version | Confirm driver name in connection string is `ODBC+Driver+18+for+SQL+Server` |

---

## 14. House rules (read once, follow always)

- Communicate in Spanish; commit messages and code in English.
- Follow `CLAUDE.md` at the repo root — it is the source of truth for conventions, terminology, and what requires approval.
- After every task: update `CHANGELOG.md`, `README.md` if affected, `TECHNICAL_DEBT.md` if debt is introduced, and propose a Conventional Commit message.
- Never commit `.env`, real client pliegos, or any kind of credential.
- Use the project terminology strictly (pliego, PCAP, PPT, licitación — see `CLAUDE.md` section 7).

---

## 15. Quick start (TL;DR for a returning developer)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
az login                       # only if token expired
python scripts/seed_users.py   # only on a fresh DB (creates tables + dev users)
uvicorn app.main:app --reload  # start the server
# open http://127.0.0.1:8000/docs
```

Open `docs/backlog/sprint-2.md` to pick the next issue. Work in a feature branch, open a PR against `main`.

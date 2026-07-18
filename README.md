# LicitAI

> Plataforma de análisis de licitaciones públicas españolas basada en IA generativa.

---

## 🇪🇸 Español

LicitAI es una plataforma RAG (Retrieval-Augmented Generation) que ayuda a empresas a analizar pliegos de licitaciones públicas (PCAP y PPT), identificar requisitos clave y generar borradores de propuesta técnica.

### Stack

- **Backend**: FastAPI + Pydantic v2 + SQLAlchemy 2.0 (Python 3.11+)
- **Frontend**: React 18 + Vite + TypeScript + Tailwind
- **IA**: Azure AI Foundry (Azure OpenAI), Azure AI Search, Azure Document Intelligence
- **Infraestructura**: Azure Storage, Azure Key Vault, Azure Application Insights

### Estructura del repositorio

```
licitai/
├── backend/      # API FastAPI
├── frontend/     # SPA React
├── infra/        # Documentación y scripts de infraestructura Azure
├── docs/         # Arquitectura, ADRs, decisiones técnicas
└── .github/      # Workflows de CI y plantillas
```

### Documentación

| Documento | Descripción |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Convenciones de desarrollo |
| [`docs/ADR/`](docs/ADR/) | Decisiones de arquitectura |
| [`docs/rag-design.md`](docs/rag-design.md) | Diseño del pipeline RAG |
| [`COMMERCIALIZATION_PLAN.md`](COMMERCIALIZATION_PLAN.md) | Plan de comercialización (privado, no distribuir) |

### Setup local

En macOS, Linux Debian/Ubuntu o Windows con WSL2:

```bash
./dev.sh
```

El script crea `backend/.venv`, instala dependencias Python y frontend, instala
Python/Node/Azure CLI/ODBC/Pango cuando falten, crea `backend/.env` desde
`.env.example`, solicita `az login` y actualiza el esquema de base de datos.
En una máquina nueva puede pedir contraseña de administrador.

Para preparar el equipo sin arrancar los servicios:

```bash
BOOTSTRAP_ONLY=1 ./dev.sh
```

#### Eval-lite (backend)

Harness de evaluación RAG (suites S3 faithfulness + S4 refusal, spec 5.3 subset).
Golden dataset etiquetado a mano en `backend/eval/golden/` (guía en su README).
Requiere credenciales Azure (`backend/.env`); desde `backend/`:

```bash
python -m eval.run --suite all --map <golden_key>=<licitacion_id>   # reporte en eval/reports/
python -m eval.run --suite all --map ... --baseline                 # estampa baseline (git limpio)
```

Deployment del juez configurable con `EVAL_JUDGE_MODEL` (por defecto `chat_pliego_4o`).

#### Frontend (pnpm)

El frontend usa **pnpm** (v11+) como único gestor de paquetes — no uses npm ni bun
(el lockfile es `pnpm-lock.yaml`). Comandos habituales desde `frontend/`:

```bash
pnpm install     # dependencias
pnpm dev         # servidor de desarrollo (proxy /api → localhost:8000)
pnpm test        # smoke tests (vitest + Testing Library + msw)
pnpm typecheck   # TypeScript estricto
pnpm build       # build de producción
```

La guía manual y los requisitos de acceso a Azure están en
[`backend/SETUP_LOCAL.md`](backend/SETUP_LOCAL.md).

---

## 🇬🇧 English

LicitAI is a RAG (Retrieval-Augmented Generation) platform that helps companies analyze Spanish public tender documents (PCAP and PPT), identify key requirements, and generate technical proposal drafts.

### Stack

- **Backend**: FastAPI + Pydantic v2 + SQLAlchemy 2.0 (Python 3.11+)
- **Frontend**: React 18 + Vite + TypeScript + Tailwind
- **AI**: Azure AI Foundry (Azure OpenAI), Azure AI Search, Azure Document Intelligence
- **Infrastructure**: Azure Storage, Azure Key Vault, Azure Application Insights

### Repository structure

```
licitai/
├── backend/      # FastAPI API
├── frontend/     # React SPA
├── infra/        # Azure infrastructure docs and scripts
├── docs/         # Architecture, ADRs, technical decisions
└── .github/      # CI workflows and templates
```

### Local setup

On macOS, Debian/Ubuntu Linux, or Windows through WSL2:

```bash
./dev.sh
```

The script creates `backend/.venv`, installs Python and frontend dependencies,
provisions Python/Node/Azure CLI/ODBC/Pango when missing, creates
`backend/.env` from `.env.example`, requests `az login`, and updates the
database schema. Use `BOOTSTRAP_ONLY=1 ./dev.sh` to prepare the machine without
starting the services.

The frontend is **pnpm-only** (lockfile: `pnpm-lock.yaml`). From `frontend/`:
`pnpm install`, `pnpm dev`, `pnpm test`, `pnpm typecheck`, `pnpm build`.

---

## License

Proprietary — all rights reserved.

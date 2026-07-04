# claude.md — Reglas para trabajar en LicitAI

> Este archivo es la fuente de verdad para cualquier asistente IA que trabaje en el proyecto.
> Se actualiza al final de cada conversación si emerge una convención nueva.

---

## 1. Contexto del proyecto

**Pliexa** (nombre comercial decidido 2026-07-04; nombre interno histórico: LicitAI) es una plataforma RAG (Retrieval-Augmented Generation) para analizar licitaciones públicas españolas. Permite subir pliegos (PCAP, PPT), procesarlos con OCR, indexarlos y consultarlos con IA generativa.

> **Regla de naming**: todo texto de cara al usuario (UI, títulos, emails, docs de cliente) usa **Pliexa**. Los identificadores internos existentes (`LicitAIError`, nombres de módulos) pueden conservar `licitai` hasta que su rewrite los toque. Recursos Azure nuevos: `pliexa` en lugar de `licitai`. Ver `plan/00-CONTEXT.md` §1.

**Funcionalidades principales:**
1. **Explicación clara** del pliego: traduce lenguaje administrativo/jurídico a comprensible.
2. **Generación de borradores** de propuesta técnica a partir del PPT.
3. **Checklist de requisitos**: extrae requisitos técnicos, económicos, administrativos y plazos.
4. **Chatbot RAG**: preguntas en lenguaje natural sobre el pliego con citas de página.
5. **Match score**: puntuación de encaje pliego-empresa con justificación.

**Naturaleza:** Producto comercial con dos tiers de despliegue (decidido 2026-07-04): tier estándar en un entorno Azure compartido con aislamiento por cliente en la capa de datos (índice + contenedor + esquema dedicados, filtro de organización), y tier dedicado premium con entorno Azure propio por cliente. El código debe ser profesional, mantenible, seguro y multi-tenant desde el diseño. Ver `plan/00-CONTEXT.md` §1.

**Origen:** Base técnica desarrollada inicialmente por Jorge Pulgar, Álvaro López y Siro Cornejo. Ver `docs/ADR/` para el historial de decisiones de arquitectura.

---

## 2. Stack tecnológico

| Capa | Tecnología |
|---|---|
| **Backend** | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic |
| **Frontend** | React 18, Vite, TypeScript, Tailwind CSS |
| **IA / LLM** | Azure AI Foundry (Azure OpenAI): `gpt-4o-mini` (T=0.2) para respuestas |
| **Embeddings** | `text-embedding-3-small` (1536 dims) vía Azure OpenAI |
| **OCR** | Azure Document Intelligence (`prebuilt-layout`) |
| **Vector Store / Search** | Azure AI Search (búsqueda híbrida keyword+vector + semantic ranker, HNSW) |
| **Almacenamiento** | Azure Blob Storage (contenedor `pliegos-raw`) |
| **Base de datos** | SQLite en local (dev), Azure-hosted en prod |
| **Secretos** | Azure Key Vault |
| **Observabilidad** | Azure Application Insights, logging JSON estructurado |
| **Auth** | JWT propio (bcrypt/argon2), expiración 24h |
| **CI/CD** | GitHub Actions (por configurar) |
| **Testing** | pytest (backend), vitest o similar (frontend) |

---

## 3. Arquitectura general

```
┌────────────────────────────────────────────────────────┐
│                     Frontend (React SPA)                │
│  Login → Lista pliegos → Subida → Detalle+Chat → Export│
└───────────────────────┬────────────────────────────────┘
                        │ HTTP (JWT en header)
                        ▼
┌────────────────────────────────────────────────────────┐
│                   Backend (FastAPI)                     │
│                                                        │
│  /api/v1/auth/*      → Auth service (JWT, bcrypt)      │
│  /api/v1/pliegos/*   → Ingestion service               │
│  /api/v1/query       → Query service (RAG)             │
│  /api/v1/pliegos/{id}/summary → Summary service        │
│  /api/v1/pliegos/{id}/match   → Match score service    │
│  /api/v1/proposals/* → Proposal generation             │
│                                                        │
│  Servicios internos:                                   │
│  ├── ingestion.py   → Upload PDF → Blob Storage        │
│  ├── ocr.py         → Document Intelligence → Chunks   │
│  ├── indexing.py     → Embeddings → AI Search          │
│  ├── query.py        → Search + LLM → Respuesta+Citas  │
│  └── proposal.py     → Generación de borradores        │
└───────┬──────────┬──────────┬──────────┬───────────────┘
        │          │          │          │
        ▼          ▼          ▼          ▼
   Azure Blob  Azure AI   Azure AI  SQLAlchemy
   Storage     Search     Foundry   (SQLite/DB)
```

### Flujo de ingesta de un pliego

```
PDF subido → Blob Storage → Document Intelligence (OCR)
  → Texto estructurado → Chunking (800 chars, 150 overlap)
  → Embeddings (text-embedding-3-small) → AI Search (índice HNSW)
  → Estado del pliego: "indexed"
```

### Flujo de consulta (RAG)

```
Pregunta del usuario + pliego_id
  → Embedding de la pregunta
  → Búsqueda híbrida en AI Search (keyword + vector + semantic ranker)
  → Top-K chunks relevantes (filtrados por pliego_id y user_id)
  → Prompt al LLM con chunks como contexto
  → Respuesta con citas inline [p. X]
```

---

## 4. Convenciones de código

### Estructura de carpetas

```
licitai/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # Endpoints (routers FastAPI)
│   │   ├── models/          # SQLAlchemy models + Pydantic schemas
│   │   ├── services/        # Lógica de negocio (ingestion, ocr, query, etc.)
│   │   ├── core/            # Config, logging, seguridad, deps compartidas
│   │   └── main.py          # Entrypoint FastAPI
│   ├── tests/
│   │   ├── fixtures/pliegos/  # Pliegos reales de prueba
│   │   └── ...
│   ├── scripts/             # Scripts auxiliares (seed, migraciones)
│   ├── alembic/             # Migraciones de DB
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/      # Componentes React
│   │   ├── pages/           # Páginas/vistas
│   │   ├── services/        # Cliente HTTP, llamadas a API
│   │   ├── types/           # Tipos TypeScript
│   │   └── App.tsx
│   └── ...
├── infra/                   # Scripts y docs de infraestructura Azure
├── docs/
│   └── ADR/                 # Architecture Decision Records
└── .github/                 # Workflows CI, templates PR/issue
```

### Naming

| Contexto | Convención |
|---|---|
| Variables y funciones Python | `snake_case` |
| Clases Python | `PascalCase` |
| Variables y funciones TypeScript | `camelCase` |
| Componentes React y tipos TS | `PascalCase` |
| Archivos Python | `snake_case.py` |
| Archivos React (componentes) | `PascalCase.tsx` |
| Archivos TS (utilidades) | `camelCase.ts` |
| Variables de entorno | `UPPER_SNAKE_CASE` |
| Branches y commits | en inglés, Conventional Commits |

### Estilo

- **Python:** seguir PEP 8. Usar Ruff como linter/formatter. Type hints en todas las funciones públicas. Docstrings en español para módulos, en inglés para funciones si se prefiere consistencia con el código.
- **TypeScript:** strict mode. No `any` salvo justificación explícita.
- **Imports:** ordenar con isort (Python) / ESLint (TS). Imports absolutos dentro del proyecto.

### Manejo de errores

- Usa excepciones custom derivadas de una base `LicitAIError` para errores de dominio.
- Nunca tragues excepciones silenciosamente. Siempre loggea antes de re-lanzar o convertir.
- Los endpoints devuelven códigos HTTP semánticos: 400 (input inválido), 401 (no autenticado), 403 (no autorizado), 404 (no encontrado), 422 (validación Pydantic), 500 (error interno).
- En errores de APIs externas (Azure), aplica retry con backoff exponencial antes de fallar.

### Logging

- Usa logging JSON estructurado (módulo `core/logging.py`).
- Niveles: `DEBUG` para flujo interno, `INFO` para eventos de negocio, `WARNING` para degradaciones, `ERROR` para fallos recuperables, `CRITICAL` para fallos que paran el servicio.
- Nunca loggees datos personales, contenido de pliegos completos ni tokens JWT.
- Incluye `pliego_id`, `user_id` y `request_id` como contexto en cada log.

---

## 5. Diseño y UI/UX del frontend

### Principio general

Este es un producto profesional para una empresa real. La interfaz debe parecer hecha por un equipo de producto, **no por una IA**. Evita el "look IA" genérico a toda costa.

### Lo que NO quiero ver

- **Bordes super redondeados** en todo (`rounded-3xl` en cada card). Usa bordes sutiles y coherentes.
- **Colores vividos y saturados** (gradientes neón, azules eléctricos, verdes lima). Usa una paleta sobria y profesional. Esto es una herramienta de trabajo para analizar licitaciones, no un dashboard de marketing.
- **Badges/pills/tags por todos lados**. Usa badges solo cuando aporten información real y escasa (ej: estado de procesamiento). No decores por decorar.
- **Páginas hipercentradas** con un card estrecho flotando en el centro de una pantalla de 27". Usa el ancho disponible de forma inteligente. Sidebars, layouts multi-columna, tablas que respiran.
- **Sombras exageradas**, glassmorphism innecesario, animaciones que no aportan.
- **Iconos decorativos** que no comunican nada. Si pones un icono, que sea funcional.

### Lo que SÍ quiero

- **Diseño limpio y funcional.** Inspiración: herramientas como Linear, Notion o el panel de Vercel. Densidad de información alta pero organizada.
- **100% responsive.** Todo debe funcionar en desktop, tablet y móvil. No hay excusa para que una vista se rompa en pantallas pequeñas. Usa breakpoints de Tailwind y testea en viewport estrecho.
- **Tipografía legible.** Jerarquía clara de tamaños. Cuerpo de texto cómodo de leer (los pliegos son documentos largos).
- **Espaciado consistente.** Usa un sistema de spacing (escala de Tailwind: `space-2`, `space-4`, `space-6`...) y no inventes valores arbitrarios.
- **Colores con propósito.** Neutrales para el 90% de la interfaz. Color de acento para acciones principales y estados. Semáforo (rojo/amarillo/verde) solo para estados reales (error/warning/success).
- **Feedback visual.** Estados de carga (skeletons, no spinners genéricos), estados vacíos con mensaje útil, estados de error con acción para recuperarse.
- **Transiciones sutiles.** Hover states, focus rings para accesibilidad, transiciones de 150-200ms. Nada que rebote, pulse o parpadee.

### Reutilización de componentes

- **Si algo se repite en más de un sitio, extráelo.** Crea un componente, un hook o una utilidad según corresponda.
- Componentes UI base en `frontend/src/components/ui/` (Button, Input, Card, Badge, Modal, etc.). Todo el proyecto los usa. Nunca repitas un botón con estilos inline.
- Hooks custom en `frontend/src/hooks/` para lógica reutilizable (ej: `useAuth`, `usePliegos`, `useDebounce`).
- Utilidades compartidas en `frontend/src/lib/` o `frontend/src/utils/`.
- Si copias y pegas un bloque de JSX o lógica, para y pregúntate si debería ser un componente. La respuesta casi siempre es sí.

---

## 6. Filosofía de desarrollo

### Arregla la raíz, no el síntoma

- **No parchees.** Si algo falla, entiende por qué falla antes de tocar código. No añadas un `if` para esquivar un caso raro si el problema real es que el modelo de datos está mal.
- **No acumules tiritas.** Cada parche rápido sobre un parche anterior crea código frágil e ilegible. Si ves que estás poniendo la tercera tirita al mismo módulo, para y refactoriza.
- **Refactoriza cuando sea necesario.** No tengas miedo de reescribir una función o reorganizar un módulo si el diseño original ya no escala. Avisa antes si el cambio es grande (ver sección 14: Lo que NO debes hacer sin preguntar).

### DRY con criterio

- **Código duplicado = deuda técnica.** Si la misma lógica existe en dos sitios, centralízala.
- Aplica DRY en backend también: servicios compartidos, utilidades, decoradores, middleware.
- Pero no sobre-abstraigas. Si dos cosas se parecen hoy pero evolucionarán distinto, está bien tener dos implementaciones. Duplicar es mejor que la abstracción incorrecta.

### Calidad sobre velocidad

- Este proyecto va a producción. El código debe ser legible dentro de 6 meses.
- Nombres descriptivos. `process_pliego_chunks` > `do_stuff`. `isAuthenticated` > `flag`.
- Funciones cortas con una responsabilidad clara. Si una función tiene más de 40-50 líneas, probablemente hace demasiado.
- Comentarios para el *por qué*, no para el *qué*. El código debería explicar el qué por sí solo.

---

## 7. Convenciones específicas del dominio

### Terminología obligatoria

Usa estos términos con precisión. No inventes sinónimos:

| Término | Significado | Notas |
|---|---|---|
| **Pliego** | Documento completo de la licitación | Término genérico que engloba PCAP y PPT |
| **PCAP** | Pliego de Cláusulas Administrativas Particulares | Condiciones contractuales, plazos, penalizaciones |
| **PPT** | Pliego de Prescripciones Técnicas | Requisitos técnicos, lo que hay que hacer |
| **Licitación** | Procedimiento completo de contratación pública | NO es sinónimo de pliego |
| **Lote** | Subdivisión de una licitación en partes independientes | Un pliego puede tener varios lotes |
| **Mesa de contratación** | Órgano que evalúa las ofertas | |
| **UTE** | Unión Temporal de Empresas | Agrupación para presentarse a una licitación |
| **Solvencia técnica** | Capacidad demostrada para ejecutar el contrato | Experiencia previa, equipo, medios |
| **Solvencia económica** | Capacidad financiera | Cifra de negocio, seguros |
| **Criterios de adjudicación** | Baremo para puntuar las ofertas | Técnicos (juicio de valor) + económicos (automáticos) |
| **PLACSP** | Plataforma de Contratación del Sector Público | Portal oficial donde se publican las licitaciones |
| **LCSP** | Ley de Contratos del Sector Público (Ley 9/2017) | Marco legal de contratación pública en España |
| **Presupuesto base de licitación** | Precio máximo que la administración pagará | IVA incluido o excluido según contexto |
| **Sobre/fichero digital** | Los licitadores presentan su oferta en sobres | Sobre 1: documentación, Sobre 2: técnico, Sobre 3: económico |
| **Proposición** / **oferta** | Respuesta del licitador al pliego | |
| **Propuesta técnica** | Documento con la solución técnica propuesta | Lo que genera LicitAI como borrador |

### Reglas de uso

- Nunca digas "documento" cuando te refieras a un "pliego". Sé específico.
- Distingue siempre entre PCAP y PPT cuando el contexto lo requiera.
- "Licitación" es el proceso, "pliego" es el documento.
- En el código, el modelo principal se llama `Pliego`, no `Document` ni `Tender`.

---

## 8. Reglas para trabajar con IA/LLMs

### Prompts del sistema

- Almacena todos los system prompts en `backend/app/prompts/` como archivos `.py` con constantes string, NO hardcodeados en el servicio.
- Nombra cada prompt con su función: `QUERY_SYSTEM_PROMPT`, `SUMMARY_SYSTEM_PROMPT`, `PROPOSAL_SECTION_PROMPT`.
- Incluye versionado en el propio prompt (comentario `# v1.2 — 2026-05-15: añadido constraint de citas`).
- Documenta en cada prompt: qué hace, qué inputs espera, qué formato de output produce.

### Diseño de prompts

- Siempre instruye al modelo a **citar la página de origen** con formato `[p. X]`.
- Siempre incluye la instrucción: "Si la información no aparece en los fragmentos proporcionados, di explícitamente que no se encuentra en el pliego. No inventes información."
- Usa few-shot examples cuando el formato de salida sea complejo (ej: checklist de requisitos).
- Limita la temperatura a **0.2 máximo** para tareas extractivas. Sube a 0.5-0.7 solo para generación creativa (borradores de propuesta).

### Evaluación de outputs

- Toda respuesta RAG debe incluir citas. Si no hay citas, es un bug.
- Validación de citas: verificar que las páginas citadas existen en el pliego.
- Loggea siempre: pregunta, chunks recuperados, respuesta generada, tiempo de respuesta. Esto permite auditoría y mejora iterativa.

### Alucinaciones

- En contexto de licitaciones públicas, una alucinación puede causar que una empresa presente una oferta incorrecta o pierda un plazo. **Esto es crítico.**
- Regla de oro: **mejor no responder que inventar**. El modelo debe decir "no encontrado" si no tiene evidencia en los chunks.
- Nunca generes datos numéricos (presupuestos, plazos, importes de solvencia) sin cita explícita del chunk fuente.

---

## 9. Reglas para el RAG

### Chunking

- **Tamaño:** ~800 caracteres con 150 de overlap.
- **Respeta límites de párrafo**: no cortes a mitad de frase.
- Si un párrafo supera 800 chars, permite chunk más largo (prioriza coherencia semántica sobre tamaño uniforme).
- Cada chunk preserva `page_number` de origen. Esto es obligatorio para las citas.

### Embeddings

- Modelo: `text-embedding-3-small` (1536 dimensiones).
- Procesamiento en batch (max 100 chunks por llamada).
- Retry con backoff exponencial si la API falla.

### Índice y búsqueda

- **Azure AI Search** con configuración HNSW.
- Búsqueda **híbrida**: keyword + vector + semantic ranker.
- Siempre filtra por `pliego_id` y `user_id`. Nunca devuelvas chunks de otro usuario o de otro pliego.
- `top_k = 5` por defecto. Ajustable según evaluación.

### Citación

- **Toda respuesta del chatbot debe poder trazarse al fragmento del pliego.**
- Formato de cita inline: `[p. X]` donde X es el número de página.
- El `QueryResponse` incluye `citations: list[Citation]` con `page_number`, `text` (fragmento), `score` (relevancia).
- En frontend, las citas son clicables y resaltan el fragmento fuente.

### Trazabilidad

- Loggea cada query RAG con: `query_id`, `user_id`, `pliego_id`, pregunta, chunks recuperados (IDs + scores), respuesta generada, latencia total.
- No loggees el contenido completo de los chunks (puede contener info sensible), solo IDs y scores.

---

## 10. Seguridad y privacidad

### Principios

- Los pliegos pueden contener información sensible (presupuestos internos, datos de empresas). Trátalos como datos confidenciales.
- Aislamiento estricto: cada usuario solo accede a sus propios pliegos, chunks e historial. Filtra siempre por `user_id` en queries a DB y AI Search.
- RGPD aplica. El usuario tiene derecho al olvido (endpoint `DELETE /api/v1/auth/me`).

### Secretos

- **Nunca** hardcodees secretos, API keys, connection strings ni contraseñas en el código.
- Todos los secretos van en Azure Key Vault (prod) o en `.env` local (dev).
- El archivo `.env` está en `.gitignore`. Usa `.env.example` como plantilla sin valores reales.
- Si alguien sube un secreto por error, se rota inmediatamente.

### Lo que NO va al repo

- `.env`, `*.pem`, `*.key`
- Pliegos reales de clientes (los de test son pliegos públicos de PLACSP)
- Datos personales de usuarios
- Logs con contenido de pliegos
- Tokens JWT

### RGPD

- Política de retención configurable (30 días por defecto).
- Tarea programada de borrado de pliegos vencidos (blob + DB + índice).
- Cifrado en tránsito (HTTPS) y en reposo (Azure Storage default).
- Documentación legal en `docs/legal/`.

---

## 11. Testing

### Backend

- Framework: `pytest`.
- Fixtures de pliegos reales en `backend/tests/fixtures/pliegos/` (públicos de PLACSP, anonimizados si necesario).
- Tests unitarios para cada servicio (`ingestion`, `ocr`, `query`, `indexing`, `auth`).
- Tests de integración para endpoints (con `httpx.AsyncClient` y TestClient de FastAPI).
- Tests específicos de aislamiento: usuario A no ve datos de usuario B.
- Mocks para APIs externas (Azure) en tests unitarios. Tests de integración contra servicios reales solo en CI con credenciales de test.

### Frontend

- Tests de componentes (vitest + React Testing Library).
- Cobertura mínima: en definición, pero todo servicio y endpoint nuevo debe tener al menos un test.

### RAG

- Test de pipeline completo: PDF → chunks → indexación → query → respuesta con citas.
- Corpus de test: 3 pliegos (1 nativo simple, 1 nativo con tablas, 1 escaneado).
- Validar que las citas referencian páginas que existen.

### Regla general

- Si añades lógica nueva, añade al menos un test que la cubra.
- No mergees código sin tests a `main` (ver Definition of Done en `CONTRIBUTING.md`).

---

## 12. Flujo post-conversación

**Aplica a CADA tarea que hagamos, sin excepción.**

Al terminar cada tarea o conversación:

### 10.1. CHANGELOG.md

Actualiza `CHANGELOG.md` en la raíz del proyecto con:

```markdown
## [Unreleased]

### YYYY-MM-DD

- **feat:** Descripción del cambio
- **fix:** Descripción del arreglo
- **refactor:** Descripción del refactor
- **docs:** Descripción del cambio de docs
- **chore:** Descripción de la tarea
```

### 10.2. README.md

Revisa si los cambios afectan a:
- Instrucciones de instalación o setup
- Variables de entorno nuevas
- Comandos nuevos
- Estructura del repo

Si sí, actualiza el README.

### 10.3. TECHNICAL_DEBT.md

Registra cualquier:
- TODO introducido en el código
- Hack temporal con justificación
- Deuda técnica consciente ("esto funciona pero debería refactorizarse porque...")
- Decisiones que se tomaron por falta de tiempo

Formato:

```markdown
## Deuda técnica

### YYYY-MM-DD — Descripción breve
- **Qué:** Qué se hizo de forma subóptima
- **Por qué:** Por qué se hizo así (restricción de tiempo, dependencia no lista, etc.)
- **Impacto:** Qué puede pasar si no se arregla
- **Propuesta:** Cómo debería arreglarse
- **Issue relacionada:** #N (si aplica)
```

### 10.4. Mensaje de commit

Propón un mensaje de commit en formato Conventional Commits, listo para copiar:

```
tipo(scope): descripción en inglés

Cuerpo opcional con contexto.

Closes #N
```

Tipos válidos: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`, `style`.

### 10.5. Actualizar este archivo

Si durante la conversación ha emergido:
- Una convención nueva
- Una decisión de arquitectura
- Una preferencia del equipo
- Un patrón que debe seguirse

Actualiza este `claude.md` para que persista.

---

## 13. Reglas de comunicación

- **Idioma:** siempre en español. Código y commits en inglés, pero toda comunicación conmigo en español.
- **Nivel de detalle:** explica el qué y el por qué. No asumas que sé cómo funciona una librería específica; si tomas una decisión técnica no obvia, justifícala brevemente.
- **Formato:** directo y estructurado. Usa bullet points, tablas y bloques de código. Nada de párrafos largos sin estructura.
- **Antes de actuar, pide confirmación cuando:**
  - El cambio sea destructivo (borrar archivos, reescribir módulos enteros).
  - Haya una decisión de arquitectura con varias opciones válidas.
  - Vayas a instalar una dependencia nueva.
  - El cambio afecte al esquema de base de datos.
  - No estés seguro de qué opción prefiero.
- **Cuando propongas algo:** presenta las opciones con pros/contras si hay más de una razonable. Recomienda una, pero déjame decidir.
- **Si algo no está claro en el backlog o en este archivo:** pregunta antes de asumir.

---

## 14. Lo que NO debes hacer sin preguntar

Estas acciones requieren **confirmación explícita mía** antes de ejecutarlas:

1. **Borrar archivos** o directorios existentes.
2. **Cambiar dependencias mayores** (nueva librería, upgrade con breaking changes, eliminar dependencia).
3. **Modificar el esquema de base de datos** (nuevos campos, tablas, migraciones).
4. **Tocar código de seguridad/auth** (JWT, middleware, permisos, hashing).
5. **Hacer commits o pushes** al repo.
6. **Cambiar la estructura de carpetas** del proyecto.
7. **Modificar prompts del sistema** que ya estén versionados y validados.
8. **Cambiar la configuración de Azure** (índices, modelos, key vault).
9. **Modificar `CONTRIBUTING.md`** o las reglas de trabajo del equipo.
10. **Introducir un nuevo patrón arquitectónico** que no esté ya en el proyecto.

**Sí puedes hacer sin preguntar:**
- Crear archivos nuevos que sigan la estructura existente.
- Añadir tests.
- Corregir bugs evidentes.
- Mejorar documentación.
- Refactors menores que no cambien la API pública.
- Formatear código.

---

## 15. Decisiones técnicas registradas

> Esta sección se actualiza conforme se toman decisiones. Las ADRs formales van en `docs/ADR/`.

| Fecha | Decisión | Justificación |
|---|---|---|
| 2026-05-07 | Chunking 800 chars / 150 overlap | Balance entre contexto suficiente para el LLM y precisión de citas |
| 2026-05-07 | gpt-4o-mini con T=0.2 para queries | Coste/rendimiento óptimo para extracción; baja temperatura para reducir alucinaciones |
| 2026-05-07 | Azure AI Search con HNSW | Búsqueda híbrida + semantic ranker integrado, sin gestionar infra adicional |
| 2026-05-07 | JWT propio (no OAuth) | MVP; en producción podría migrarse a Azure AD B2C si el cliente lo requiere |
| 2026-05-07 | ~~SQLite en dev~~ (obsoleto) | Reemplazado: ver fila siguiente |
| 2026-05-25 | Azure SQL Server compartido en dev (vía `pyodbc` + ODBC Driver 18) | Paridad dev/prod y datos compartidos por el equipo. La BD de dev NO es local: es el servidor Azure compartido |
| 2026-05-25 | Esquema sin Alembic: `Base.metadata.create_all` vía `scripts/seed_users.py` | Migraciones eliminadas; con un solo entorno y un responsable de esquema, las migraciones eran sobrecarga. `create_all` no altera tablas existentes — cambios de esquema se coordinan a mano |
| 2026-06-17 | Estado comercial de licitación separado del `status` de pipeline: nueva columna `estado` + `resultado` (BIT) | `status` ya significa estado de procesamiento (processing/indexed/error). El workflow comercial (elaborando→revisión→entregada→resuelta) es ortogonal. El estado terminal `resuelta` lleva un booleano `resultado` (Ganada/Perdida) en vez de dos estados, por preferencia del cliente |
| 2026-06-19 | Memoria: ensamblado de la propuesta determinista en código (no LLM). El LLM solo redacta la introducción; las secciones se cosen verbatim | Un agente ensamblador que re-emite todo el contenido lo trunca ("[El documento continúa…]"). El cosido en código no puede truncar y garantiza el mismo estilo (normaliza fences/encabezados de cada agente) |
| 2026-06-19 | Chat de consultas con sesiones: nueva columna `queries.session_id` (NVARCHAR 36, nullable), generado en cliente | Hilos diferenciados con memoria acotada por sesión, sin contaminación entre conversaciones. Nullable para no romper filas previas (sesión heredada). Requiere ALTER manual en Azure (sin Alembic, §15 fila 2026-05-25) |

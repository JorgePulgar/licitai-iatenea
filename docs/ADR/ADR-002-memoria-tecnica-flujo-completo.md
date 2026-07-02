# ADR-002 — Memoria Técnica: flujo completo (esquema → propuesta → chat → export)

- **Estado:** Propuesto
- **Fecha:** 2026-06-05
- **Autores:** Jorge (con asistencia IA)
- **Decisores:** Equipo LicitAI (Álvaro, Jorge, Siro) + PO (cliente)
- **Supersede:** [ADR-001](ADR-001-memoria-tecnica-esqueleto.md)

---

## Contexto

ADR-001 limitó la feature al **esqueleto** (estructura de secciones), dejando la
redacción para S4. Tras revisarlo, el objetivo real de producto es un **flujo
completo end-to-end**: que el usuario obtenga una **Memoria Técnica redactada y
exportable**, iterando con un agente conversacional.

El flujo deseado:

```
1. Generar ESQUEMA           → agente esquema → JSON de secciones (estructura)
2. Generar PROPUESTA         → recibe esquema final (editado por el usuario)
                               → agente propuesta → Markdown redactado
3. CHAT de refinado          → recibe markdown actual + input del usuario
                               → agente conversacional (con histórico)
                               → devuelve markdown completo editado + texto de chat
4. EXPORT                    → Markdown → PDF
```

Esto **fusiona** lo que ADR-001 separaba (esqueleto S3 / redacción S4): ambos se
construyen ahora. El backend de esqueleto ya en `main` (ADR-001, `propose_sections`,
tabla `memoria_sections`) **se reutiliza** como el paso 1.

## Decisión

### 1. Cuatro endpoints, todos bajo `/api/v1/licitaciones/{licitacion_id}/memoria`

La **clave de sesión es `licitacion_id + user_id`** (una memoria por licitación).
**No se usa `session_id`**: no hay borradores paralelos por licitación.

| # | Método · Ruta | Body | Respuesta |
|---|---|---|---|
| 1 | `POST /esquema` | `{ message? }` | `{ reply, esquema: MemoriaSectionDraft[] }` |
| 2 | `POST /propuesta` | `{ esquema: MemoriaSectionDraft[] }` | `{ markdown }` |
| 3 | `POST /chat` | `{ markdown, message }` | `{ markdown, texto_chat }` |
| 4 | `POST /export` | `{ markdown? }` | `application/pdf` |

- **Endpoint 1** = el `propose_sections` actual (agente esquema). Sin cambios de fondo.
- **Endpoint 3** sustituye el `/chat` de iteración de esqueleto: ahora el chat edita
  el **Markdown** redactado, no la estructura.
- El backend **persiste** el markdown e historial; el front manda el markdown actual
  en cada turno (fuente de verdad compartida, se reconcilia con lo persistido).

### 2. Fix 1 (CRÍTICO) — grounding obligatorio en propuesta y chat

Los agentes de **propuesta** (2) y **chat** (3) reciben SIEMPRE como contexto:

- **Chunks del PPT** vía `hybrid_search` (qué exige el pliego). Reutiliza el índice
  RAG existente, solo lectura.
- **`CompanyProfile`** del usuario (qué ofrece la empresa).
- El **esquema** (estructura aprobada) y, en el chat, el markdown actual.

Sin estos inputs el agente redactaría inventando → oferta incorrecta. Regla §8:
**mejor "no consta" que alucinar**. Datos numéricos (importes, plazos, solvencia)
solo si vienen del pliego o del perfil.

### 3. Fix 2 — persistir el esquema estructurado además del Markdown

El Markdown es el documento entregable, pero la **estructura** (criterio mapeado,
puntos, presupuesto de páginas) debe seguir siendo **dato consultable**, no prosa:

- **`memoria_sections`** (ya existe) = esquema estructurado, fuente de verdad de la
  estructura y del mapeo al juicio de valor / límite de páginas del PCAP.
- **`memoria_documents`** (NUEVA tabla) = el Markdown redactado (una fila por
  licitación).
- **`memoria_chat_messages`** (ya existe) = histórico del chat, clave `licitacion_id`.

Así no se pierde el control de "¿cubro todos los criterios valorables?" ni "¿respeto
el límite de páginas?" (clave: excederlo descalifica).

### 4. Fix 3 (incluido) — guardrail anti-drift en el chat

El agente de chat devuelve el **markdown completo editado** cada turno. Riesgo: al
pedir un cambio puntual, el modelo reescribe y degrada el resto. Mitigación:

- El system prompt instruye: **"aplica SOLO el cambio pedido; el resto del documento
  se devuelve VERBATIM, sin reescribir."**
- Temperatura baja (0.2) para edición; más alta (0.5–0.7) solo en la generación
  inicial de propuesta (creativa).
- **Aceptado para MVP** el coste/latencia de devolver el documento entero. Trabajo
  futuro: edición por secciones o por diffs para documentos largos (30–50 págs).

### 5. Tres prompts versionados (`prompts/memoria.py`)

- `MEMORIA_ESQUEMA_PROMPT` (el actual `MEMORIA_PROPOSE_SYSTEM_PROMPT`, renombrado).
- `MEMORIA_PROPUESTA_PROMPT` — redacta Markdown desde esquema + PPT + perfil.
- `MEMORIA_CHAT_PROMPT` — edita el Markdown con histórico, guardrail anti-drift.

### 6. Export a PDF

Markdown → PDF. **Requiere una dependencia nueva** (gate §14.2 — a confirmar). El PDF
del MVP **no garantiza** el formato obligatorio del PCAP (fuentes, márgenes, límite
de páginas estrictos); es un entregable de trabajo, no la versión final certificable.
Trabajo futuro: plantillas con CSS que respeten el PCAP.

### 7. El RAG no cambia (se mantiene de ADR-001)

- No se indexan las memorias (riesgo de contaminación con el pliego, §8).
- Propuesta y chat **leen** el índice del PPT existente; no escriben.
- La reutilización semántica de prosa de memorias `won` sigue diferida (futuro).

## Modelo de datos

Tabla nueva (gate §14.3 — confirmar antes de tocar `domain.py`):

**`memoria_documents`**

| Columna | Atributo | Tipo | Notas |
|---|---|---|---|
| `id` | `id` | `String(36)` PK | |
| `licitacion_id` | `licitacion_id` | `String(36)` FK→`licitaciones.id` `ondelete=CASCADE`, **unique**, index | una por licitación |
| `user_id` | `user_id` | `String(36)` index | §10 |
| `markdown` | `markdown` | `Text` nullable | documento redactado |
| `created_at` / `updated_at` | … | `DateTime(tz)` | |

`memoria_sections` y `memoria_chat_messages` se mantienen sin cambios.

## Alternativas consideradas

| Alternativa | Por qué se descarta |
|---|---|
| Mantener solo esqueleto (ADR-001) | No cumple el objetivo de producto: el usuario quiere la memoria redactada y exportable. |
| Artefacto solo estructurado (sin Markdown) | El chat de refinado de prosa y el export PDF necesitan un documento; Markdown es el formato natural. |
| Solo Markdown (sin esquema persistido) | Se pierde el mapeo a criterios/puntos/páginas → no se puede controlar el juicio de valor ni el límite de páginas. |
| `session_id` (multi-borrador) | Innecesario: una memoria por licitación. `licitacion_id + user_id` basta. |
| Indexar memorias en el RAG | Contaminación con el pliego (§8). Diferido a futuro, índice separado y gated en `won`. |

## Consecuencias

**Positivas**
- Feature completa end-to-end (estructura → redacción → refinado → export).
- Iteración conversacional real (markdown completo + histórico).
- Reutiliza el backend de esqueleto ya en `main` y el RAG/perfil existentes.
- Estructura mapeada al juicio de valor sigue siendo dato consultable.

**Negativas / riesgos**
- Adelanta S4 (más alcance ahora).
- Devolver el documento entero por turno: coste/latencia/drift en docs largos
  (mitigado con guardrail; rediseño futuro por secciones).
- PDF del MVP no certifica formato PCAP.
- 1 tabla nueva + 1 dependencia nueva (PDF) → gates §14.2/§14.3.

## Gates pendientes (CLAUDE.md §14)

1. **§14.3 — schema:** OK a `memoria_documents` antes de tocar `domain.py`; Álvaro
   materializa con `create_all`.
2. **§14.2 — dependencia:** elegir librería de export Markdown→PDF antes de instalar.

## Referencias

- [ADR-001](ADR-001-memoria-tecnica-esqueleto.md) (superseded).
- `docs/backlog/sprint-3.2.md` — contrato de API previo (a actualizar con estos 4 endpoints).
- `backend/app/services/memoria.py`, `prompts/memoria.py` — base reutilizable.
- `services/query.py` (`hybrid_search`), `services/match.py` (`CompanyProfile`).

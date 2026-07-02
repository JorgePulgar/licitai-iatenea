# ADR-001 — Memoria Técnica: esqueleto curado por usuario

> ⚠️ **SUPERSEDED por [ADR-002](ADR-002-memoria-tecnica-flujo-completo.md) (2026-06-05).**
> El alcance pasó de "solo esqueleto" a flujo completo (esquema → propuesta en
> Markdown → chat de refinado → export PDF). Lo que sigue vigente: almacenamiento
> en DB (no RAG), grounding reutilizando criterios extraídos, aislamiento
> per-usuario, sin indexar memorias. Lo que cambia: ya se redacta contenido (no
> solo estructura). Ver ADR-002.

- **Estado:** Superseded por ADR-002
- **Fecha:** 2026-06-05
- **Autores:** Jorge (con asistencia IA)
- **Decisores:** Equipo LicitAI (Álvaro, Jorge, Siro) + PO (cliente)
- **Sprint:** S3 (precede a la generación de propuesta de S4)

---

## Contexto

En las licitaciones públicas españolas, la **Memoria Técnica** es el documento que
la empresa licitadora presenta para demostrar *cómo* ejecutará el contrato. Es la
**única base del *juicio de valor*** (criterios subjetivos de adjudicación), que
en contratos complejos puede valer el 30–50 % de la puntuación total. Una memoria
mal estructurada o que no mapee a los criterios del PCAP pierde la licitación,
independientemente del precio.

Queremos una nueva sección en la página de detalle de la licitación (**"Memoria
técnica"**) con un chat que **proponga las secciones** (el esqueleto/estructura) de
la Memoria Técnica para esa licitación. Lógica de tres ramas:

1. Si la licitación ya tiene secciones propuestas → devolverlas.
2. Si no, pero el usuario tiene memorias de licitaciones previas → usarlas como
   plantilla para proponer.
3. Si no hay previas → el LLM propone con criterio propio, **grounded en el pliego**
   (criterios de adjudicación del PCAP) y preguntando al usuario cuando falte info.

Esta feature **precede** al botón "Generar propuesta" (S4), hoy stub en
`LicitacionDetailPage.tsx`.

---

## Decisión

### 1. Alcance: solo esqueleto, no redacción

La feature produce y cura el **esqueleto** de la Memoria Técnica: lista ordenada de
secciones con metadatos (qué cubre, criterio de adjudicación mapeado, puntos
máximos, presupuesto de páginas). **No redacta contenido.** El relleno de cada
sección es responsabilidad de la **generación de propuesta de S4** (`proposal.py`),
que consumirá este esqueleto.

Se reserva un campo `content` (nullable, vacío ahora) en el modelo para que S4 lo
rellene **sin cambio de esquema futuro**.

### 2. Almacenamiento: tablas DB, no índice RAG

El esqueleto y el historial de chat se guardan en **tablas SQL**
(`memoria_sections`, `memoria_chat_messages`), consistente con el resto del proyecto
(summaries, requirements, match ya son tablas).

La reutilización de memorias previas (rama 2) se resuelve por **agregación SQL**
sobre las secciones del propio usuario (frecuencia de títulos), **no por retrieval
semántico**. No requiere índice vectorial.

### 3. El RAG no cambia

- El índice de Azure AI Search **no se modifica**.
- El grounding (rama 3) **lee** el índice existente del pliego (no escribe).
- **No** se indexan las memorias técnicas. Mezclar borradores propios con los
  pliegos (fuente autoritativa) en el mismo índice causaría contaminación: el
  chatbot RAG podría recuperar nuestro propio borrador y tratarlo como exigencia
  del pliego → alucinación (prohibido por §8 de CLAUDE.md).

### 4. Grounding reutiliza la extracción de requisitos

Los criterios de adjudicación **ya se extraen** a `PliegoRequirement`
(`categoria='criterio_adjudicacion'`, con puntos y juicio de valor). La propuesta de
secciones **reutiliza** esas filas como contexto primario; sólo cae a `hybrid_search`
sobre el PCAP si aún no se han extraído (DRY, §6).

### 5. Aislamiento per-usuario

Las memorias previas usadas como plantilla son **solo del propio usuario**
(`user_id`). Respeta el aislamiento estricto de §10. Se filtra por `user_id` en
todas las consultas y endpoints.

---

## Alternativas consideradas

| Alternativa | Por qué se descarta |
|---|---|
| **Esqueleto + redacción en esta feature** | Solapa con `proposal.py` (S4). Mezcla dos responsabilidades. Se separa estructura de redacción. |
| **Memorias previas en un índice RAG nuevo (ahora)** | La reutilización del esqueleto es agregación de títulos (SQL), no búsqueda semántica. Un índice sería sobre-ingeniería, coste y riesgo de aislamiento sin beneficio. |
| **Indexar memorias junto a los pliegos** | Contaminación de fuente: borrador propio confundido con exigencia del pliego → alucinación. |
| **Plantilla compartida equipo/org** | Rompe el aislamiento §10. Se opta por per-usuario; revisable si el cliente lo pide explícitamente. |
| **Tabla de plantillas dedicada** | Innecesaria: la plantilla se deriva al vuelo de las secciones aceptadas del usuario. Auto-mejora sin infra extra. |

---

## Consecuencias

**Positivas**
- Separación limpia esqueleto (S3) ↔ redacción (S4).
- Cero cambios en Azure: sin nuevos índices, deployments ni recursos.
- Reutiliza RAG y extracción de requisitos existentes (DRY).
- Esqueleto mapeado a criterios de juicio de valor → secciones que puntúan.
- Respeta aislamiento §10.

**Negativas / riesgos**
- El grounding depende de que el PCAP esté indexado y tenga criterios legibles. Si
  falta PCAP o es imagen-only, se degrada a plantilla / preguntar al usuario (la
  rama 3 ya lo cubre).
- Los puntos de cada criterio viven en texto libre de `PliegoRequirement`, no en
  campo estructurado; el LLM de memoria los parsea del contexto.
- Schema change (2 tablas) requiere coordinación manual en la DB compartida (§15).

---

## Trabajo futuro (fuera de scope)

- **S4 — reutilización de prosa**: cuando se finalice/exporte una propuesta en S4,
  indexar su contenido en un **índice separado**, **per-usuario**, **gated en
  memorias `won`** (solo las ganadas), con granularidad por sección. Permitiría
  retrieval semántico de "¿cómo redactamos la sección de calidad la última vez?".
  Esto sí justifica un índice RAG nuevo — pero es decisión propia, futura.
- **Propuesta de esqueleto por similitud de pliego**: buscar pliegos pasados
  semánticamente parecidos (mismo sector) y reusar su esqueleto. Embebe el *pliego*
  (ya indexado), no la memoria; join pliego↔esqueleto en DB.

---

## Referencias

- CLAUDE.md §3 (arquitectura), §6 (DRY), §8 (alucinaciones), §10 (aislamiento),
  §14.3 (cambios de esquema), §15 (sin Alembic).
- `backend/app/services/requirements.py` — extracción de criterios de adjudicación.
- `backend/app/services/query.py` — `hybrid_search` (grounding).

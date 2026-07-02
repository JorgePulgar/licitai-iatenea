# Deuda técnica

### 2026-06-23 — El paginador del editor de Memoria es una aproximación independiente del PDF
- **Qué:** El editor (`PaginationGuides` en `RichDocumentEditor.tsx`) simula la paginación midiendo bloques en px y empujándolos con `margin-top`; el PDF lo genera WeasyPrint con layout real (`memoria_export.py`). Son dos motores distintos: aunque ahora el editor ya no acumula drift (badge y contenido caen exactos sobre su propia rejilla), su **partición de páginas puede no coincidir al 100% con la del PDF** (fuentes px↔pt, métricas de línea, colapso de márgenes). Además, el **salto de página manual** (`pageBreak`) sigue usando un spacer con altura, que rompe el margin-collapsing → reintroduce ~pocos px de drift por cada salto manual (los automáticos ya no).
- **Por qué:** Unificar editor y export contra un mismo motor (p. ej. paged.js como vista previa fiel, ya existe `PaginatedMarkdown` + `memoriaPaged.css` espejo del CSS de WeasyPrint) es un cambio de alcance/UX mayor; se priorizó arreglar el drift de raíz en los saltos automáticos (la queja real) con cambio acotado.
- **Impacto:** El usuario puede ver el corte de página ligeramente distinto entre editor y PDF; con muchos saltos **manuales** el badge de esos saltos puede desviarse unos px. Los saltos automáticos y el contenido están alineados al px.
- **Propuesta:** (a) Convertir `pageBreak` al mismo patrón collapse-safe (altura 0 + `margin-top` en el bloque siguiente, badge anclado), o (b) cablear `PaginatedMarkdown` (paged.js) como vista previa "lo que ves = lo que exportas" junto al editor TipTap. Evaluar (b) si se quiere fidelidad total editor↔PDF.

### 2026-06-19 — Chunking por secciones requiere reindexar los pliegos existentes
- **Qué:** Los nuevos campos `Chunk.seq` y `Chunk.section_heading` (y los campos `seq`/`section_heading` del índice AI Search) solo se pueblan al re-procesar un pliego. Los chunks ya indexados con el chunker antiguo no tienen `seq`, así que la **expansión por vecinos los ignora** (degradación elegante): siguen recuperándose y citándose, pero sin traer sus contiguos. El beneficio pleno (secciones puras + vecinos) solo aplica a pliegos reingestados.
- **Por qué:** Reindexar consume llamadas a Azure Document Intelligence (coste) sobre la cuenta de dev compartida y afecta a datos del equipo; se acordó dejarlo como paso aparte y aprobado (no automático).
- **Impacto:** Mezcla de calidad mientras conviven chunks viejos y nuevos. La búsqueda funciona en ambos; solo cambia la completitud de las citas.
- **Propuesta:** Ejecutar `scripts/reindex_pliegos.py --all` (ya implementado; sincroniza el índice + re-OCR + reindexa) sobre los pliegos existentes una vez validado en el corpus de test (§11). Pendiente de ejecución (cuesta llamadas DI sobre la cuenta compartida). Hasta entonces, los pliegos nuevos ya nacen con el chunking por secciones.
- **Estado actual (2026-06-19):** reindex `--all` ejecutado; 3 licitaciones pequeñas quedaron limpias (100% `seq`) pero **2 grandes (>1000 chunks) quedaron con duplicados** (chunks viejos sin `seq` + nuevos) por el bug de troceo de 1000 docs (ya corregido en `indexing.py`). **Acción pendiente:** volver a ejecutar `reindex_pliegos.py <licitacion_id>` sobre esas 2 (`2F62BF79-…` y `3E02AFBD-…`) ahora que el borrado pagina correctamente, para eliminar los chunks duplicados.

### 2026-06-19 — Columna `queries.session_id` requiere ALTER manual en Azure
- **Qué:** El modelo `Query` añade `session_id` (NVARCHAR 36, nullable, indexado) para las sesiones del chat de consultas. `create_all` no altera tablas existentes (§15), así que hay que correr el ALTER a mano en la BD compartida antes de desplegar el backend. SQL idempotente entregado (T-SQL: `IF COL_LENGTH('dbo.queries','session_id') IS NULL ... ALTER TABLE ... ADD session_id NVARCHAR(36) NULL` + `CREATE INDEX IX_queries_session_id`).
- **Por qué:** Un solo entorno Azure SQL, sin Alembic, esquema coordinado a mano (decisión 2026-05-25).
- **Impacto:** Si se despliega el backend sin el ALTER, `POST /query/` y `GET /query/{id}/sessions` fallan (columna inexistente). Re-ejecutar el SQL es seguro (idempotente).
- **Propuesta:** Incluir el `ADD COLUMN` en el runbook de despliegue.

### 2026-06-19 — El retrieval del chat RAG no usa el historial de la conversación
- **Qué:** Se dio memoria al chat de consultas reinyectando los turnos previos al LLM, pero `hybrid_search` sigue buscando solo con la pregunta *actual* en crudo. Una pregunta de seguimiento elíptica ("¿y eso cuánto cuesta?", "¿y el plazo?") recupera chunks contra un texto sin contexto, así que el LLM tiene memoria pero puede no recibir los fragmentos correctos.
- **Por qué:** El fix mínimo y de bajo riesgo era el threading de historial en los mensajes (la queja era "no recuerda"). Enriquecer la query de retrieval (query rewriting / condensación con el último turno) implica otra llamada al LLM o heurística, con riesgo de meter ruido.
- **Impacto:** Seguimientos muy elípticos pueden traer evidencia pobre y responder peor o "no encontrado", aunque el dato exista. No afecta a preguntas autocontenidas.
- **Propuesta:** Condensar pregunta+historial en una "standalone question" (mini-prompt T=0) antes de `hybrid_search`, o concatenar el último turno de usuario a la query de búsqueda. Evaluar contra el corpus de test (§11).

### 2026-06-17 — Columnas `estado`/`resultado`/`deadline` requieren ALTER manual en Azure
- **Qué:** El modelo `Licitacion` añade `estado` (NVARCHAR 30, default `elaborando`), `resultado` (BIT null) y `deadline` (DATE null). `create_all` no altera tablas existentes (§15), así que hay que correr el ALTER a mano en la BD compartida antes de desplegar el backend. Las licitaciones antiguas quedan en `elaborando` (por el DEFAULT) y sin `deadline`.
- **Por qué:** Un solo entorno Azure SQL, sin Alembic, esquema coordinado a mano (decisión 2026-05-25).
- **Impacto:** Si se despliega el backend sin el ALTER, las queries sobre `licitaciones` fallan (columnas inexistentes). El SQL entregado es idempotente (`COL_LENGTH ... IS NULL`), así que re-ejecutarlo es seguro.
- **Propuesta:** Incluir el `ADD COLUMN` en el runbook de despliegue / futuro proceso de migraciones.

### 2026-06-17 — Sin CHECK constraint sobre `estado`; validación solo en la app
- **Qué:** Los valores válidos de `estado` se validan en el endpoint PATCH (`LICITACION_ESTADOS`), no con un CHECK en BD. Igual con la coherencia `resultado` solo-si-`resuelta`.
- **Por qué:** El CHECK existente en `db.sql` (`CK_licitaciones_status`) ya está desincronizado con el runtime (valores `analysing/bidding/...` vs `processing/indexed/...`), señal de que la BD real no lo aplica. Añadir un CHECK nuevo arriesgaba conflicto con el estado real de la tabla.
- **Impacto:** Una escritura directa a BD (fuera de la API) podría meter un `estado` inválido. La UI nunca lo hace.
- **Propuesta:** Al normalizar el esquema, añadir `CK_licitaciones_estado CHECK (estado IN (...))` y limpiar el CK de `status` obsoleto.

### 2026-06-16 — Extracción de título añade una llamada LLM por ingesta
- **Qué:** `process_pliego` ahora hace, además del OCR, una llamada extra a Azure DI-free pero **+1 llamada LLM** (`extract_title_llm`) cuando el role tagging de DI no detecta el título (frecuente en PCT). Es síncrona dentro del pipeline de ingesta.
- **Por qué:** El título vive en el PDF y DI no lo etiqueta de forma fiable en portadas con el texto partido en muchas líneas. El LLM (gpt-4o-mini, T=0) reconstruye el título de forma robusta. Se prioriza la vía rápida (role tagging, sin coste) y solo se cae al LLM si falla.
- **Impacto:** Coste/latencia marginal por documento en la ingesta. Si Azure OpenAI está caído, el título queda `None` (la UI cae al filename) — degradación aceptable, no rompe la ingesta.
- **Propuesta:** Si el volumen de ingesta crece, mover la extracción de título a un paso asíncrono o cachear por hash de la primera página. Evaluar si merece la pena un modelo más barato/local solo para esta tarea.

### 2026-06-16 — `doc_title` se llena en pliegos nuevos; los antiguos requieren backfill manual
- **Qué:** La columna `Pliego.doc_title` se rellena automáticamente en cada ingesta nueva, pero los pliegos ya existentes quedan `NULL` hasta correr `scripts/backfill_doc_titles.py`. El ALTER de la columna (`NVARCHAR(512)`) se aplica a mano en la BD compartida (sin Alembic, §15).
- **Por qué:** Decisión de esquema del equipo (un solo entorno Azure SQL, cambios coordinados a mano). `create_all` no altera tablas existentes.
- **Impacto:** Tras desplegar, hay una ventana en la que pliegos antiguos muestran "—" en la columna Título hasta que alguien corre el backfill. Si se olvida el ALTER antes de desplegar el backend, las queries sobre `pliegos` fallan.
- **Propuesta:** Cuando se adopte un proceso de migraciones (o el seed idempotente), incluir el `ADD/ALTER COLUMN doc_title` y un paso de backfill documentado en el runbook de despliegue.

### 2026-06-12 — Reparto de requisitos por sección mediante solapamiento léxico
- **Qué:** En la redacción multi-agente (`_select_requisitos_for_section` en `services/memoria.py`), cada agente de sección recibe los `PliegoRequirement` "relevantes" elegidos por **solapamiento de tokens** (intersección de palabras tras quitar stopwords) entre el texto de la sección y la descripción del requisito. Es un heurístico léxico, no semántico.
- **Por qué:** Los requisitos no están etiquetados por sección y montar un retrieval semántico (embeddings req↔sección) o un agente clasificador añadía coste/latencia a un fan-out que ya hace N+1 llamadas LLM. El solapamiento léxico es barato (sin red) y suficiente para títulos descriptivos.
- **Impacto:** Sinónimos y paráfrasis se pierden (p. ej. sección "Equipo" no captará un requisito redactado como "personal adscrito" si no comparten tokens). Un requisito relevante puede no llegar a su sección → la memoria podría no cubrir una obligación del pliego. Riesgo acotado: los requisitos también están implícitos en la evidencia del PPT que cada agente recupera.
- **Propuesta:** Etiquetar cada `PliegoRequirement` con la(s) sección/criterio a los que responde en el momento de la extracción, o rankear req↔sección por similitud de embeddings (reusar `text-embedding-3-small`). Evaluar con el corpus de test si el heurístico deja requisitos obligatorios fuera.

### 2026-06-12 — El ensamblador depende de que el LLM no reescriba las secciones
- **Qué:** `_assemble_memoria` instruye al agente ensamblador a **preservar verbatim** el contenido de cada sección (solo cose, añade título/intro/transiciones). No hay verificación programática de que el texto de salida contenga el de entrada; se confía en el cumplimiento del prompt (T=0.3).
- **Por qué:** Igual que el guardrail anti-drift del chat: validar diffs sección a sección entre entrada y salida del ensamblador es complejo (el agente legítimamente añade conectores e intro). MVP.
- **Impacto:** El ensamblador podría resumir o alterar contenido de una sección sin que se detecte; en el peor caso introduce drift o pierde una cita `[p. X]`.
- **Propuesta:** Validación post-ensamblado: comprobar que cada sección de entrada está sustancialmente presente (p. ej. ratio de solapamiento de n-gramas o que todas las citas `[p. X]` sobreviven); si no, fallback a la concatenación cruda ya implementada.

### 2026-06-10 — Subida de plantillas síncrona y sin previsualización del resumen
- **Qué:** `POST /api/v1/templates/` ejecuta extracción de texto (Azure DI) + agente de resumen profundo en línea, bloqueando la respuesta HTTP. En PDFs largos (50+ págs) puede tardar 30+ s; el frontend muestra "Procesando…" sin progreso real. Si el LLM falla, la plantilla queda persistida con `summary=NULL` y no hay endpoint de reintento.
- **Por qué:** Para un MVP claro y consistente — el usuario espera ver la plantilla "lista" al volver. Asíncrono añadía estado intermedio (`pending`/`processing`/`ready`/`failed`) y polling sin valor inmediato.
- **Impacto:** UX pobre con archivos grandes; el usuario no sabe si la subida sigue viva. Si el resumen falla, se inyecta el texto bruto truncado (degradación silenciosa) y nadie lo regenera.
- **Propuesta:** Mover el resumen a un background task (FastAPI `BackgroundTasks` o cola tipo `pliegos` pipeline). Añadir campo `status` (`processing` | `ready` | `failed`), endpoint `POST /api/v1/templates/{id}/regenerate-summary`, y polling/SSE en frontend. Mostrar progreso real al usuario.

### 2026-06-10 — Plantillas comparten contenedor de Blob Storage con pliegos
- **Qué:** Las plantillas se suben al contenedor `pliegos-raw` bajo prefijo `company-templates/{user_id}/`. Comparten infra con los pliegos.
- **Por qué:** Evita crear y aprovisionar un contenedor nuevo + SAS distinto en Azure para una feature en MVP. El aislamiento por usuario se hace por prefijo + filtro por `user_id` en la DB.
- **Impacto:** Políticas de retención, ACL y borrado masivo del contenedor afectan a las dos cosas a la vez. Para auditorías que filtren por contenedor (no por prefijo) se mezclan ambos artefactos.
- **Propuesta:** Crear contenedor dedicado `company-templates-raw` con política de retención propia y SAS independiente cuando se escale. Migrar URLs existentes con un script.

### 2026-06-05 — Export PDF requiere libs nativas de WeasyPrint (GTK/Pango)
- **Qué:** `app/services/memoria_export.py` usa WeasyPrint, que en runtime necesita librerías nativas (GTK/Pango/cairo). En Windows sin GTK falla con `OSError: cannot load library 'libgobject-2.0-0'`.
- **Por qué:** Se eligió WeasyPrint por calidad de CSS y futura fidelidad al formato PCAP. Sus deps nativas no son pip-installables en Windows.
- **Impacto:** El endpoint `/memoria/export` devuelve 503 (manejado limpio) si el sistema no tiene Pango. El entorno virtual por sí solo no puede aportar estas librerías.
- **Estado local:** `dev.sh` instala y valida Pango automáticamente en macOS y Debian/Ubuntu antes de arrancar.
- **Pendiente:** Incluir Pango explícitamente en la futura imagen Docker de producción y en CI; el repositorio todavía no tiene Dockerfile.

### 2026-06-05 — Chat de memoria devuelve el Markdown completo cada turno (drift en docs largos)
- **Qué:** El agente de chat (`edit_propuesta_chat`) devuelve el documento Markdown entero en cada turno. En memorias largas (30-50 págs) esto es costoso/lento y arriesga **drift** (el modelo reescribe secciones no pedidas).
- **Por qué:** Modelo más simple para MVP; el front siempre tiene el documento completo. Mitigado con guardrail anti-drift en el prompt y T=0.2.
- **Impacto:** Coste/latencia altos y posible degradación de secciones no editadas en documentos grandes.
- **Propuesta:** Edición por secciones o por diffs (el front manda solo la sección a editar; el back recompone). Ver ADR-002 §4 "trabajo futuro".

### 2026-06-05 — Export PDF no respeta el formato obligatorio del PCAP
- **Qué:** El PDF generado usa un CSS sobrio genérico (A4). No garantiza fuentes, márgenes ni límite de páginas que el PCAP impone (excederlos descalifica).
- **Por qué:** MVP: entregable de trabajo, no la versión final certificable.
- **Impacto:** El PDF exportado no se puede presentar tal cual a la mesa de contratación sin revisión manual de formato.
- **Propuesta:** Plantillas CSS por tipo de PCAP / parametrización de márgenes, fuente y límite de páginas. Validación de extensión.

### 2026-06-03 — DI extraía solo 2 páginas de cada pliego — RESUELTO (2026-06-03)
- **Qué:** Azure Document Intelligence devolvía solo las 2 primeras páginas de cada PDF (PCAP de 85 págs → págs 1–2; PPT de 9 págs → págs 1–2). RAG no podía responder sobre criterios de adjudicación, presupuesto, solvencia ni plazos: ese contenido vive en páginas posteriores que DI nunca extraía.
- **Por qué (root cause):** El recurso de Document Intelligence estaba en el tier gratuito **F0**, que limita el análisis a **las 2 primeras páginas** de cualquier documento (límite no ajustable, confirmado en [service-limits](https://learn.microsoft.com/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0#model-usage)). La llamada devolvía 200 OK con `result.pages == 2`, sin error visible. El diagnóstico previo culpó al chunking; el síntoma real era el tier. F0 también limita el tamaño de fichero a 4 MB.
- **Diagnóstico:** `backend/scripts/diag_di.py` imprime `len(result.pages/paragraphs/tables)` y los números de página vistos. Mostró `DI result.pages: 2` frente a `pypdf page count: 85`, confirmando el corte en origen.
- **Resolución:** Álvaro subió el recurso de DI a tier **Standard (S0)** (hasta 2000 págs/doc, fichero 500 MB). Mismo endpoint/clave, sin cambio de código. Tras re-indexar ambas licitaciones (`scripts/reindex_licitacion.py`), las queries devuelven respuestas correctas con citas de páginas posteriores.
- **Nota:** El rework de `ocr.py` (paragraphs + celdas de tabla agrupadas por página, commit `72b119f`) era correcto pero quedaba enmascarado por el límite F0; ahora aporta valor real en páginas con tablas.
- **Issue relacionada:** desbloquea calidad RAG para cualquier pliego de más de 2 páginas

### 2026-05-31 — App Insights connection string solo en `.env` — RESUELTO (2026-05-31)
- **Qué:** `APPLICATIONINSIGHTS_CONNECTION_STRING` se leía solo de `.env` (dev), sin carga desde Key Vault.
- **Resolución:** Secreto `APPINSIGHTS-CONNECTION-STRING` creado en `kv-licitai-dev` y cargado en `load_from_keyvault()` vía `load_secret(...)`. Verificado: con el valor eliminado de `.env`, el setting se rellena desde KV. Ya no se necesita `.env` para telemetría — cualquier dev autenticado contra el vault la tiene. Ahora consistente con el resto de secretos.
- **Issue relacionada:** LIC-101 / LIC-103

### 2026-05-27 — Requirements extraction is lazy (not pre-generated at index time)
- **Qué:** Los requisitos se extraen la primera vez que se consulta el tab de requisitos o se calcula el match score. No se generan automáticamente al indexar.
- **Por qué:** Mismo patrón lazy que summary — más seguro y evita consumir tokens si el usuario nunca consulta esa funcionalidad.
- **Impacto:** Primera consulta de requisitos o match score tarda más (~5-10s extra por la llamada LLM de extracción).
- **Propuesta:** Pre-generar requisitos al final del pipeline cuando status=indexed, igual que se debería hacer con el summary.

### 2026-05-27 — Checklist interactivo de requisitos indeterminados pendiente
- **Qué:** El match score marca requisitos como "indeterminado" pero el usuario no puede marcarlos manualmente como cumplidos/no cumplidos desde el frontend.
- **Por qué:** Se priorizó el flujo completo perfil→requisitos→match. La interacción manual requiere persistir respuestas del usuario y recalcular el score.
- **Impacto:** El usuario ve los indeterminados pero no puede resolver la ambigüedad sin actualizar su perfil.
- **Propuesta:** Añadir endpoint `PATCH /api/v1/licitaciones/{id}/match/resolve` que reciba respuestas manuales, las persista, y recalcule el score.

### 2026-05-27 — Las 3 nuevas tablas se crean vía create_all (sin migración)
- **Qué:** `company_profiles`, `pliego_requirements`, y `match_results` se crean con `Base.metadata.create_all`, no con migración Alembic.
- **Por qué:** El proyecto no usa Alembic (decisión registrada en CLAUDE.md §15). `create_all` no altera tablas existentes.
- **Impacto:** Si se necesita cambiar el esquema de estas tablas, hay que coordinar a mano (DROP + recrear, o ALTER manual).
- **Propuesta:** Seguir la convención actual. Evaluar Alembic si el equipo crece o los cambios de esquema se hacen frecuentes.

### 2026-05-25 — LIC-034: summary not pre-generated at index time
- **Qué:** Summary caching is lazy (generated on first request). Backlog says it should be triggered at end of `pipeline.py` when status becomes `indexed`.
- **Por qué:** Lazy approach was safer for this session — pre-generating at pipeline end requires passing a DB session into `pipeline.py`, which would widen its scope.
- **Impacto:** First user request for summary still hits the LLM. Subsequent users of the same licitacion would be served from cache.
- **Propuesta:** At end of `pipeline.py` (after setting status=indexed), call `generate_summary` and persist to `licitacion_summaries`. Issue: LIC-034.

### 2026-05-23 — Manual retry in embeddings.py not migrated to tenacity
- **Qué:** `_embed_batch_with_retry` in `embeddings.py` uses a manual asyncio-sleep loop instead of tenacity.
- **Por qué:** LIC-061b scope was LLM calls only; embeddings already had retry logic.
- **Impacto:** Inconsistent retry strategy between embeddings (manual) and LLM/DI (tenacity). No jitter on embedding retries.
- **Propuesta:** Migrate `_embed_batch_with_retry` to use tenacity decorator in S4.

### 2026-05-23 — setup_logging called after config startup logs
- **Qué:** `config.py` logs during `settings.load_from_keyvault()` before `setup_logging()` is called in lifespan. Those startup messages are not JSON-formatted.
- **Por qué:** `config.py` is imported at module load time, before FastAPI lifespan runs.
- **Impacto:** Startup log messages (Key Vault, JWT fallback) lose structured JSON format.
- **Propuesta:** Call `setup_logging()` earlier (e.g., at top of `main.py` before imports) or move Key Vault loading into lifespan.

### 2026-05-23 — run_retention.py has no cron scheduling mechanism
- **Qué:** `scripts/run_retention.py` is a CLI script with no built-in scheduling. Must be invoked externally.
- **Por qué:** Azure Functions timer trigger or cron setup requires infra config (Álvaro's scope).
- **Impacto:** If not wired up, expired pliegos accumulate indefinitely.
- **Propuesta:** Wire `run_retention.py` to Azure Functions timer trigger in S4 infra work. Issue: LIC-063.

### 2026-05-23 — LIC-058 unanswerable detection uses string matching
- **Qué:** `_is_unanswerable` detects LLM no-info responses by checking hardcoded Spanish marker strings.
- **Por qué:** Simple, reliable, no extra LLM call needed. Works for current prompt constraints.
- **Impacto:** Brittle if the system prompt changes or the LLM uses slightly different phrasing.
- **Propuesta:** Evaluate adding a structured LLM output (JSON with `answerable: bool`) in S4.

### 2026-05-17 — fetchPliego obtiene la lista completa para buscar por ID
- **Qué:** `fetchPliego(id)` llama a `fetchPliegos(0, 200)` y filtra en cliente en vez de usar un endpoint `GET /api/v1/pliegos/{id}`.
- **Por qué:** El backend no expone un endpoint individual de pliego. Se priorizó la conexión de los demás endpoints.
- **Impacto:** Rendimiento degradado cuando el usuario tenga muchos pliegos. Transferencia innecesaria de datos.
- **Propuesta:** Añadir endpoint `GET /api/v1/pliegos/{pliego_id}` en el backend y usar `fetchPliego` directamente.

### 2026-05-17 — Auth token solo en localStorage
- **Qué:** El JWT se almacena en `localStorage` sin opción de `sessionStorage` ni cookies HttpOnly.
- **Por qué:** Simplicidad para el MVP. El checkbox "Recordar sesión" no cambia el comportamiento aún.
- **Impacto:** Vulnerable a XSS. En producción debería migrarse a cookies HttpOnly o sesiones server-side.
- **Propuesta:** Implementar cookies HttpOnly con SameSite=Strict cuando se despliegue en producción.

# Golden dataset — guía de etiquetado (spec 5.3 §1, subset DM9)

Un fichero `<key>.yaml` por licitación fixture. El etiquetado es manual (Jorge),
una sola vez por pliego (~2 h). El harness (`python -m eval.run`) rechaza
ficheros en `status: draft`: al terminar de etiquetar, cambia a `status: labeled`.

## Qué etiquetar (subset DM9: S3 faithfulness + S4 refusal)

1. **`qa`** — 15–25 preguntas extractivas **cuya respuesta SÍ está en el pliego**
   (mínimo 10 para `labeled`). Los esqueletos traen las 6 universales de
   `scripts/eval_rag.py`; verifica que cada una es respondible en ESTE pliego
   (si no, bórrala) y añade preguntas específicas del contenido.
   - `expected_pages` / `expected_answer` son opcionales en DM9 (alimentarán
     S1/S2). Si ya estás leyendo el pliego, rellenarlos ahora ahorra una segunda
     pasada. Valores numéricos: normalizados (ej. `1234567.89`).
2. **`unanswerable`** — 5 preguntas **plausibles** cuya respuesta NO está en el
   pliego (mínimo 3). Es la parte que exige leer el pliego: «¿exige ISO 27001?»
   solo vale si el pliego no la menciona. Evita preguntas absurdas — el momento
   demo «no lo encuentro» debe ser realista.

## Reglas

- **Versionado**: cualquier cambio de etiquetas ⇒ sube `dataset_version` ⇒
  baseline nuevo obligatorio (los scores dejan de ser comparables).
- `id` únicos dentro del fichero (`q01…`, `u01…`).
- `documents` mapea cada `document_type` (pcap | ppt | anexo) a su PDF en
  `tests/fixtures/pliegos/` — el juez S3 lee el texto real de la página citada
  de ese PDF (pypdf; solo PDF nativos — un escaneado necesitará texto por
  página de Document Intelligence, deuda registrada).
- Los pliegos fixture son documentos públicos de PLACSP — committeables.

## Estado

| Fichero | Licitación | Estado |
|---|---|---|
| `mentorias-turismo.yaml` | Servicio mentorización empresas turísticas — Impulso Digital 2026, NASERTIC (PRTR) | draft — **pre-etiquetado por Claude 2026-07-18** (18 qa + 5 unanswerable); pendiente revisión de Jorge → labeled |
| `renfe-lab-ia-2026-00048.yaml` | Operación y evolución del Laboratorio de IA — RENFE (exp. 2026-00048) | draft — **pre-etiquetado por Claude 2026-07-18** (18 qa + 5 unanswerable); pendiente revisión de Jorge → labeled |
| _(3º pliego)_ | por elegir en PLACSP (idealmente escaneado, para variedad) | pendiente |

### Cómo revisar un pre-etiquetado (Jorge)

1. Abre el PDF y comprueba por muestreo: ¿cada `expected_answer` es correcta y está
   en las `expected_pages` indicadas? (páginas = numeración del PDF, no la impresa).
2. Las `unanswerable` son la parte crítica: confirma que el pliego de verdad NO
   responde cada una (la ausencia se verificó por búsqueda + lectura, pero el ojo
   humano manda).
3. Ajusta lo que proceda y cambia `status: draft` → `labeled`.

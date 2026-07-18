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
| `mentorias-turismo.yaml` | Servicio mentorías digitalización turismo (PRTR) | draft — pendiente etiquetar |
| `obras-2026-00048.yaml` | Expediente 2026/00048 (PCP + Anexo I) | draft — pendiente etiquetar (título por confirmar) |
| _(3º pliego)_ | por elegir en PLACSP (idealmente escaneado, para variedad) | pendiente |

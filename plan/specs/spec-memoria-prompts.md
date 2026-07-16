# Spec MP — Memoria drafting prompt suite (quality)

> Fable-written, 2026-07-05. Complements `prompts-hardened.md` (security) — this spec covers QUALITY of the flagship feature. Applied at DM8 (spec-demo-minimal) and measured by eval suite S6 (spec-5.3). Prompts in Spanish (product language), stored per CLAUDE.md §8 (versioned constants in `backend/app/prompts/memoria.py`). Temperatures: esquema 0.2 · drafting 0.5 · refine 0.4 · coherence 0.2.
> **The one rule that sells the product**: the draft NEVER invents company capabilities. Anything not present in the corpus/profile becomes an explicit gap marker `[COMPLETAR: …]`. A draft that flags its gaps is trustworthy; a draft that fills them is a liability. This is also exactly what eval S6's fabrication check measures.

## 1. Esquema extraction — `MEMORIA_ESQUEMA_PROMPT` (v2)

Input: PPT chunks (retrieved: secciones de estructura de la memoria + criterios de adjudicación). Output: JSON esquema.

```text
# v2.0 — 2026-07-05: reescritura de calidad (spec-MP §1)
Eres un consultor experto en licitaciones públicas españolas. A partir de los fragmentos del Pliego de Prescripciones Técnicas (PPT) y del PCAP proporcionados, extrae la ESTRUCTURA EXIGIDA para la memoria técnica.

Reglas:
1. Si el pliego exige una estructura concreta (apartados, orden, límites de páginas), reprodúcela EXACTAMENTE, con su numeración original. No la mejores ni la reordenes.
2. Si el pliego no fija estructura, propón una basada en los CRITERIOS DE ADJUDICACIÓN sujetos a juicio de valor: un apartado por criterio, ordenados por peso descendente. Marca esta situación con "estructura_impuesta": false.
3. Para cada apartado indica: título, numeración, criterio de adjudicación al que responde (con su peso si consta), límite de extensión si consta, y la página del pliego donde se define [p. X].
4. Si un dato no aparece en los fragmentos, usa null. No inventes pesos, límites ni apartados.

Devuelve SOLO JSON válido:
{"estructura_impuesta": bool, "limite_total_paginas": int|null, "apartados": [{"numero": str, "titulo": str, "criterio": str|null, "peso": str|null, "limite": str|null, "fuente_pagina": int|null}]}
```

## 2. Section drafting — `MEMORIA_SECTION_PROMPT` (v2)

Input per call: apartado (from esquema) + pliego chunks relevant to its criterio + company corpus chunks (profile, past projects, certs) + tone param. One section per call (control + citability), coherence pass after (§4).

```text
# v2.0 — 2026-07-05: grounding estricto + marcadores de hueco (spec-MP §2)
Eres un redactor senior de memorias técnicas para licitaciones públicas españolas. Redacta el apartado "{titulo}" de la memoria técnica.

CONTEXTO DEL PLIEGO (lo que se exige y cómo se puntúa):
{pliego_chunks}

CAPACIDADES REALES DE LA EMPRESA (única fuente permitida sobre la empresa):
{corpus_chunks}

REGLAS INNEGOCIABLES:
1. Solo puedes afirmar sobre la empresa lo que aparece en CAPACIDADES REALES. Prohibido inventar proyectos, clientes, certificaciones, cifras, plantilla o experiencia.
2. Si el apartado necesita información de la empresa que NO está en el contexto, escribe el marcador [COMPLETAR: descripción concreta de lo que falta] en ese punto y sigue redactando. Los marcadores son un servicio al cliente, no un fallo.
3. Responde a lo que el criterio de adjudicación puntúa, en el orden en que el pliego lo describe. Cada requisito del pliego que abordes, referéncialo: (requisito del PCAP/PPT, p. X).
4. Extensión: {limite}. Tono: {tono}. [ejecutivo = directo, orientado a beneficios para el órgano | técnico = preciso, metodológico, con detalle operativo | comercial = persuasivo sin adjetivos vacíos]
5. Español formal administrativo-profesional. Sin superlativos huecos ("líder", "excelencia", "de vanguardia"). Cada afirmación de capacidad, respaldada por un dato del corpus.
6. Estructura interna: párrafos cortos; listas solo cuando el pliego pida enumeraciones; nada de introducciones genéricas ("En el presente apartado se procede a...").

Empieza directamente con el contenido del apartado.
```

## 3. Chat refine — `MEMORIA_REFINE_PROMPT` (v2)

```text
# v2.0 — 2026-07-05 (spec-MP §3)
Eres el mismo redactor que produjo el borrador. El usuario pide un cambio sobre el apartado actual.

APARTADO ACTUAL:
{seccion}

CONTEXTOS (pliego + capacidades de la empresa): {contexts}

Aplica EXCLUSIVAMENTE el cambio pedido: "{instruccion}". Conserva todo lo demás, incluidas referencias (p. X) y marcadores [COMPLETAR: …] que sigan siendo válidos. Las reglas de grounding del borrador siguen vigentes: nada sobre la empresa que no esté en contextos; huecos → [COMPLETAR: …]. Si la instrucción pide inventar datos de la empresa que no constan, indícalo y ofrece el marcador en su lugar.

Devuelve el apartado completo revisado.
```

## 4. Coherence pass — `MEMORIA_COHERENCE_PROMPT` (v1, new)

One call over the assembled draft, AFTER all sections. Output: issues list, NOT a rewrite (human decides).

```text
# v1.0 — 2026-07-05 (spec-MP §4)
Revisa esta memoria técnica completa como un revisor de calidad previo a la entrega. NO la reescribas. Devuelve una lista JSON de incidencias:
- contradicciones entre apartados (plazos, equipos, cifras que no cuadran)
- repeticiones sustanciales entre apartados
- requisitos del esquema sin respuesta en su apartado
- marcadores [COMPLETAR: …] pendientes (lista completa, con apartado)
- afirmaciones sobre la empresa sin respaldo aparente (sospecha de invención) — márcalas como "verificar"

{"incidencias": [{"tipo": "contradiccion|repeticion|requisito_sin_cubrir|completar_pendiente|verificar", "apartado": str, "detalle": str}]}
```

## 5. Retrieval recipe per section (implementation note)

- Pliego side: hybrid_search filtered to the licitación, query = criterio title + apartado title; top_k 6.
- Corpus side: hybrid_search over company knowledge (profile + past memorias + certs), query = apartado title + key nouns of the criterio; top_k 6. If corpus side returns <2 chunks → prepend a section-level warning to the UI ("poco material de empresa para este apartado") — sets expectations before the user reads gap markers.
- Both contexts labeled distinctly in the prompt (as in §2) — the model must never confuse pliego statements with company capabilities.

## 6. Eval hooks (S6, spec-5.3)

- Fabrication check: with a deliberately thin company-profile fixture, drafted sections must contain ZERO capability claims absent from the fixture, and ≥1 correctly-placed `[COMPLETAR: …]` where the fixture is silent. This is the hard gate.
- Structure check: esquema JSON matches the fixture PPT's exigencia section-for-section.
- Judge rubric (coverage/coherence/tono) scores 1–5; baseline per spec-5.3 §5.

## 7. Opus review checklist

- [ ] Prompts stored versioned in `prompts/memoria.py`; old texts deleted in the same PR (they're inventory-adjacent — new file is a rewrite, not an edit).
- [ ] Section calls are per-apartado, never whole-memoria-in-one-call.
- [ ] `[COMPLETAR: …]` markers render visibly in the FE (styled, not lost in text) and are listed by the coherence pass.
- [ ] Pliego/corpus contexts injected under their exact labeled headers — no mixing.
- [ ] Temperature per task as header states; deployment names from config (5.3 rule).
- [ ] Eval S6 fabrication test implemented with the thin-profile fixture and passing before DM8 is declared done.
- [ ] prompts-hardened.md delimiters/anti-injection wrapper applied AROUND these prompts (security layer composes with quality layer, not replaced by it).

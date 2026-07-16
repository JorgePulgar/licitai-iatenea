"""
Servicio de Memoria Técnica — reescrito desde spec funcional (DM5, spec-demo-minimal §2).

Contrato (síncrono, sin cola; el worker de 4.1 podrá invocar estas funciones tal cual
porque no dependen de la request: reciben ids + sesión de BD explícitos):

- ``propose_esquema(licitacion_id, user_id, title, user_message, db)``
    → ``MemoriaEsquemaResponse`` {reply, esquema[]}. Extrae la ESTRUCTURA EXIGIDA
      del pliego (prompt v2, spec-memoria-prompts §1; no persiste). Grounding:
      fragmentos de estructura del PPT + criterios de adjudicación (los ya
      extraídos en ``pliego_requirements``; fallback búsqueda sobre el PCAP),
      fenceados como datos no confiables. El ``reply`` conversacional se
      construye en código a partir del JSON del LLM.
- ``draft_propuesta(licitacion_id, user_id, title, esquema, db, session_factory)``
    → ``MemoriaDocument`` persistido. Redacción por sección EN PARALELO (un agente
      LLM por apartado, semáforo de concurrencia); el documento final se cose de
      forma DETERMINISTA en código (las secciones se preservan verbatim; el LLM solo
      redacta la introducción). Una sección fallida degrada a marcador, no aborta;
      si fallan todas, error.
- ``refine_document(doc_id, licitacion_id, user_id, current_markdown, instruction,
  db, session_factory)`` → ``(markdown, reply)``. Edición vía chat con histórico por
      documento; persiste el turno y el Markdown editado.
- Esquema persistido: ``list_sections`` / ``replace_sections`` / ``patch_section`` /
  ``delete_section``. Documentos: ``list_documents`` / ``get_document`` /
  ``update_document``. Historial: ``list_chat_history``.

Sin soporte de plantillas (CompanyTemplate): ese flujo pertenece a 3.2b y su código
actual es co-autoría pendiente de rewrite — no se importa en la ruta de demo (00-CONTEXT §2).

Las escrituras posteriores a llamadas LLM usan sesión fresca de ``session_factory``
(la conexión de la request puede caducar durante los minutos de retrieval + LLM).
"""

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.domain import (
    CompanyProfile,
    MemoriaChatMessage,
    MemoriaDocument,
    MemoriaSection,
    PliegoRequirement,
)
from app.models.schemas import (
    MemoriaEsquemaResponse,
    MemoriaSectionDraft,
    MemoriaSectionResponse,
)
from app.prompts.memoria import (
    MEMORIA_COHERENCE_PROMPT,
    MEMORIA_ESQUEMA_PROMPT,
    MEMORIA_INTRO_PROMPT,
    MEMORIA_REFINE_PROMPT,
    MEMORIA_SECTION_PROMPT,
)
from app.services.embeddings import get_openai_client
from app.services.match import build_profile_text
from app.services.query import hybrid_search

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"

# Temperaturas por tarea (spec-memoria-prompts, cabecera): esquema 0.2 ·
# redacción 0.5 · refinado 0.4 · coherencia 0.2.
ESQUEMA_TEMPERATURE = 0.2
DRAFT_TEMPERATURE = 0.5
REFINE_TEMPERATURE = 0.4
COHERENCE_TEMPERATURE = 0.2
INTRO_TEMPERATURE = 0.3
INTRO_MAX_TOKENS = 400

# Tono por defecto de la redacción (spec-MP §2: ejecutivo | tecnico | comercial).
DEFAULT_TONE = "técnico"
VALID_TONES = frozenset({"ejecutivo", "técnico", "tecnico", "comercial"})


def normalize_tone(tone: str | None) -> str:
    """Tono validado contra el enum del prompt; fuera de enum → tono por defecto
    (al prompt nunca viaja texto arbitrario del cliente en este placeholder)."""
    return tone if tone and tone.lower() in VALID_TONES else DEFAULT_TONE

# Nº máximo de agentes de sección simultáneos (cuota TPM/RPM de Azure OpenAI).
DRAFT_CONCURRENCY = 5
# Chunks del pliego por apartado (retrieval específico, spec-MP §5: top_k 6).
SECTION_EVIDENCE_TOP_K = 6
# Chunks para el grounding del esquema (estructura PPT / criterios PCAP).
CRITERIOS_FALLBACK_TOP_K = 8
# Chunks del PPT para el contexto global del chat de refinado.
REFINE_CONTEXT_TOP_K = 20
# Requisitos máximos inyectados a cada agente de sección.
SECTION_MAX_REQUISITOS = 6
# Turnos previos del chat de refinado que se reinyectan al LLM.
REFINE_HISTORY_LIMIT = 20

# Marcador con el que se degrada una sección cuyo agente falló (no se aborta el doc).
SECTION_FAILURE_MARKER = "_[COMPLETAR: sección no generada — reintenta la propuesta]_"


# ═══════════════════════════════════════════════════════════════════════════
# Esquema persistido (CRUD de secciones)
# ═══════════════════════════════════════════════════════════════════════════

def _section_row_query(db: Session, licitacion_id: str, user_id: str):
    return db.query(MemoriaSection).filter(
        MemoriaSection.licitacion_id == licitacion_id,
        MemoriaSection.user_id == user_id,
    )


def get_sections(licitacion_id: str, user_id: str, db: Session) -> list[MemoriaSectionResponse]:
    """Secciones guardadas de la licitación, en orden de lectura."""
    rows = (
        _section_row_query(db, licitacion_id, user_id)
        .order_by(MemoriaSection.sort_order.asc())
        .all()
    )
    return [MemoriaSectionResponse.model_validate(r) for r in rows]


def save_sections(
    licitacion_id: str,
    user_id: str,
    drafts: list[MemoriaSectionDraft],
    db: Session,
) -> list[MemoriaSectionResponse]:
    """Acepta el esquema: reemplaza íntegramente las secciones previas por ``drafts``."""
    _section_row_query(db, licitacion_id, user_id).delete()

    now = datetime.now(timezone.utc)
    rows = [
        MemoriaSection(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            user_id=user_id,
            title=d.title,
            description=d.description,
            criterio_adjudicacion=d.criterio_adjudicacion,
            max_puntos=d.max_puntos,
            page_budget=d.page_budget,
            sort_order=d.sort_order if d.sort_order is not None else position,
            status="accepted",
            source="user",
            created_at=now,
            updated_at=now,
        )
        for position, d in enumerate(drafts)
    ]
    db.add_all(rows)
    db.commit()

    rows.sort(key=lambda r: r.sort_order)
    return [MemoriaSectionResponse.model_validate(r) for r in rows]


def update_section(
    licitacion_id: str,
    user_id: str,
    section_id: str,
    changes: dict[str, Any],
    db: Session,
) -> MemoriaSectionResponse | None:
    """Edición parcial de una sección. ``None`` si no existe o no es del usuario."""
    row = (
        _section_row_query(db, licitacion_id, user_id)
        .filter(MemoriaSection.id == section_id)
        .first()
    )
    if row is None:
        return None

    for field, value in changes.items():
        if value is not None and hasattr(row, field):
            setattr(row, field, value)
    # Editar a mano marca la sección como "edited" salvo que el patch fije status.
    if "status" not in changes:
        row.status = "edited"
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return MemoriaSectionResponse.model_validate(row)


def delete_section(licitacion_id: str, user_id: str, section_id: str, db: Session) -> bool:
    """Elimina una sección del esquema. ``False`` si no existe o no es del usuario."""
    deleted = (
        _section_row_query(db, licitacion_id, user_id)
        .filter(MemoriaSection.id == section_id)
        .delete()
    )
    db.commit()
    return deleted > 0


# ═══════════════════════════════════════════════════════════════════════════
# Fase 1 — esquema (extracción de la estructura exigida, no persiste)
# ═══════════════════════════════════════════════════════════════════════════

def _chunks_as_text(chunks: list[dict[str, Any]]) -> str:
    """Chunks → bloque de texto con etiqueta de página, en orden de lectura."""
    if not chunks:
        return ""
    ordered = sorted(chunks, key=lambda c: c.get("page_number") or 0)
    return "\n\n".join(
        f"[p. {c.get('page_number', '?')}] {c['text']}" for c in ordered
    )


async def _esquema_grounding(licitacion_id: str, user_id: str, db: Session) -> str:
    """
    Contexto para extraer la estructura exigida (spec-MP §1): fragmentos del PPT
    sobre la estructura de la memoria + criterios de adjudicación (los ya
    extraídos en `pliego_requirements`; si no hay, búsqueda sobre el PCAP).
    """
    estructura_chunks = await hybrid_search(
        "estructura de la memoria técnica, apartados exigidos, índice de la memoria, "
        "límite de páginas, formato de presentación de la oferta técnica",
        licitacion_id,
        user_id,
        top_k=CRITERIOS_FALLBACK_TOP_K,
        document_type="ppt",
    )
    blocks = []
    if estructura_chunks:
        blocks.append(_chunks_as_text(estructura_chunks))

    extracted = (
        db.query(PliegoRequirement)
        .filter(
            PliegoRequirement.licitacion_id == licitacion_id,
            PliegoRequirement.categoria == "criterio_adjudicacion",
        )
        .all()
    )
    if extracted:
        blocks.append(
            "CRITERIOS DE ADJUDICACIÓN (extraídos del pliego):\n"
            + "\n".join(
                f"- {r.descripcion}" + (f" [p. {r.pagina}]" if r.pagina else "")
                for r in extracted
            )
        )
    else:
        criterios_chunks = await hybrid_search(
            "criterios de adjudicación, juicio de valor, puntuación de la memoria técnica",
            licitacion_id,
            user_id,
            top_k=CRITERIOS_FALLBACK_TOP_K,
            document_type="pcap",
        )
        if criterios_chunks:
            blocks.append(_chunks_as_text(criterios_chunks))

    return "\n\n".join(blocks)


def _first_number(raw: Any) -> float | None:
    """Primer número de un valor libre del LLM ("60 puntos" → 60.0). None si no hay."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    match = re.search(r"\d+(?:[.,]\d+)?", str(raw))
    return float(match.group().replace(",", ".")) if match else None


def _drafts_from_apartados(raw: list[Any]) -> list[MemoriaSectionDraft]:
    """
    Apartados del JSON v2 (spec-MP §1) → drafts del contrato del producto.
    Mapeo: numero+titulo → title · criterio → criterio_adjudicacion · peso →
    max_puntos (número extraído) · limite → page_budget (número extraído) ·
    fuente_pagina → description "[p. X]".
    """
    drafts: list[MemoriaSectionDraft] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        titulo = str(item.get("titulo") or "").strip()
        if not titulo:
            continue
        numero = str(item.get("numero") or "").strip()
        title = f"{numero}. {titulo}" if numero and not titulo.startswith(numero) else titulo

        fuente = item.get("fuente_pagina")
        description = f"Definido en el pliego [p. {fuente}]" if fuente else None

        page_budget = _first_number(item.get("limite"))
        drafts.append(
            MemoriaSectionDraft(
                title=title,
                description=description,
                criterio_adjudicacion=item.get("criterio") or None,
                max_puntos=_first_number(item.get("peso")),
                page_budget=int(page_budget) if page_budget else None,
                sort_order=position,
            )
        )
    return drafts


def _esquema_reply(estructura_impuesta: bool, count: int, limite_total: Any) -> str:
    """Mensaje conversacional para el FE (el JSON v2 del LLM ya no lo trae)."""
    if count == 0:
        return (
            "No he encontrado en el pliego una estructura exigida ni criterios "
            "suficientes para proponer apartados. Revisa que el pliego esté indexado."
        )
    base = (
        f"El pliego exige una estructura concreta: {count} apartados, reproducidos con su numeración original."
        if estructura_impuesta
        else f"El pliego no impone estructura; propongo {count} apartados a partir de los criterios de adjudicación."
    )
    limite = _first_number(limite_total)
    if limite:
        base += f" Límite total de la memoria: {int(limite)} páginas."
    return base


async def propose_esquema(
    licitacion_id: str,
    user_id: str,
    title: str,
    user_message: str,
    db: Session,
) -> MemoriaEsquemaResponse:
    """Extrae la estructura exigida de la memoria (sin persistir). Ver docstring de módulo."""
    started = time.monotonic()

    grounding = await _esquema_grounding(licitacion_id, user_id, db)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — esquema de memoria no disponible.")
        return MemoriaEsquemaResponse(
            reply="El servicio de propuesta de secciones no está disponible en este momento.",
            esquema=[],
        )

    # Los fragmentos del pliego son texto no confiable → fenceados (1.8).
    user_content = (
        f"Licitación: '{title}'\n"
        + (f"Indicaciones del usuario: {user_message}\n" if user_message else "")
        + f"\n<fragmentos_pliego>\n{grounding or 'Sin fragmentos disponibles.'}\n</fragmentos_pliego>"
    )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=ESQUEMA_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": MEMORIA_ESQUEMA_PROMPT},
                {"role": "user", "content": user_content},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido del LLM en esquema de memoria de {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error proponiendo esquema de memoria de {licitacion_id}: {e}", exc_info=True)
        raise

    esquema = _drafts_from_apartados(payload.get("apartados", []))
    reply = _esquema_reply(
        bool(payload.get("estructura_impuesta")),
        len(esquema),
        payload.get("limite_total_paginas"),
    )

    logger.info(
        "Esquema de memoria propuesto",
        extra={
            "licitacion_id": licitacion_id,
            "esquema_count": len(esquema),
            "estructura_impuesta": bool(payload.get("estructura_impuesta")),
            "has_grounding": bool(grounding),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": LLM_MODEL,
        },
    )
    return MemoriaEsquemaResponse(reply=reply, esquema=esquema)


# ═══════════════════════════════════════════════════════════════════════════
# Fase 2 — redacción de la propuesta (un agente por sección + cosido en código)
# ═══════════════════════════════════════════════════════════════════════════

_WORD = re.compile(r"[a-záéíóúñü0-9]+")
_EMPTY_WORDS = frozenset({
    "de", "la", "el", "los", "las", "un", "una", "y", "o", "a", "en", "del", "al",
    "que", "con", "por", "para", "su", "sus", "se", "lo", "es", "como", "más",
})


def _keywords(text: str) -> set[str]:
    """Palabras significativas de un texto (minúsculas, ≥3 chars, sin vacías)."""
    return {
        w for w in _WORD.findall((text or "").lower())
        if len(w) >= 3 and w not in _EMPTY_WORDS
    }


def _section_topic(section: MemoriaSectionDraft) -> str:
    """Texto que describe de qué va la sección (para retrieval y asignación)."""
    return " ".join(
        filter(None, [section.title, section.description, section.criterio_adjudicacion])
    )


def _assign_requisitos(
    section: MemoriaSectionDraft, requisitos: list[PliegoRequirement]
) -> str:
    """
    Requisitos más afines a la sección por solapamiento de palabras clave.
    Una sola carga de BD para todo el fan-out; cada agente ve solo los suyos.
    """
    topic = _keywords(_section_topic(section))
    if not topic or not requisitos:
        return ""

    ranked = sorted(
        (
            (len(topic & _keywords(r.descripcion)), r)
            for r in requisitos
            if topic & _keywords(r.descripcion)
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    lines = []
    for _score, r in ranked[:SECTION_MAX_REQUISITOS]:
        page = f" [p. {r.pagina}]" if r.pagina else ""
        optional = "" if r.es_obligatorio else " (deseable)"
        lines.append(f"- {r.descripcion}{page}{optional}")
    return "\n".join(lines)


def _default_profile_context(user_id: str, db: Session) -> str:
    """Perfil de empresa por defecto del usuario, como texto para el LLM."""
    profile = (
        db.query(CompanyProfile)
        .filter(CompanyProfile.created_by == user_id, CompanyProfile.is_default == True)  # noqa: E712
        .first()
    )
    if not profile:
        return "No hay perfil de empresa configurado."
    return build_profile_text(profile)


def _section_limite(section: MemoriaSectionDraft) -> str:
    """Instrucción de extensión para el prompt (spec-MP §2, placeholder {limite})."""
    if section.page_budget:
        return f"máximo {section.page_budget} páginas"
    if section.max_puntos:
        return "proporcional al peso del criterio en el baremo"
    return "la necesaria para responder al criterio, sin relleno"


def _pliego_context_for_section(
    evidence: str, requisitos_block: str, section: MemoriaSectionDraft
) -> str:
    """Bloque de pliego del apartado: metadatos del criterio + evidencia + requisitos."""
    parts = []
    if section.criterio_adjudicacion:
        peso = f" (peso: {section.max_puntos})" if section.max_puntos is not None else ""
        parts.append(f"Criterio de adjudicación del apartado: {section.criterio_adjudicacion}{peso}")
    if section.description:
        parts.append(f"Alcance indicado en el esquema: {section.description}")
    parts.append(evidence or "Sin fragmentos del pliego para este apartado.")
    if requisitos_block:
        parts.append(f"Requisitos del pliego afines al apartado:\n{requisitos_block}")
    return "\n\n".join(parts)


async def _draft_one_section(
    client: Any,
    licitacion_id: str,
    user_id: str,
    licitacion_title: str,
    section: MemoriaSectionDraft,
    requisitos: list[PliegoRequirement],
    profile_context: str,
    tone: str,
    gate: asyncio.Semaphore,
) -> str:
    """
    Redacta el Markdown de UN apartado con el prompt v2 (spec-MP §2): contexto del
    pliego y capacidades de la empresa bajo sus cabeceras etiquetadas, fenceados.
    Retrieval por apartado (spec-MP §5): query = título + criterio, top_k 6, sin
    filtro de documento. Si el LLM falla, degrada con marcador (nunca aborta).
    """
    async with gate:
        evidence_chunks = await hybrid_search(
            _section_topic(section) or section.title,
            licitacion_id,
            user_id,
            top_k=SECTION_EVIDENCE_TOP_K,
        )
        prompt = MEMORIA_SECTION_PROMPT.format(
            titulo=section.title,
            pliego_chunks=_pliego_context_for_section(
                _chunks_as_text(evidence_chunks),
                _assign_requisitos(section, requisitos),
                section,
            ),
            corpus_chunks=profile_context,
            limite=_section_limite(section),
            tono=tone,
        )

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                temperature=DRAFT_TEMPERATURE,
                messages=[
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": f"Redacta ahora el apartado \"{section.title}\" "
                                   f"de la memoria para la licitación '{licitacion_title}'.",
                    },
                ],
            )
            markdown = (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(
                f"Agente de sección falló ('{section.title}', licitación {licitacion_id}): {e}",
                exc_info=True,
            )
            markdown = ""

        return markdown or f"## {section.title}\n\n{SECTION_FAILURE_MARKER}"


async def _draft_intro(client: Any, licitacion_title: str, section_titles: list[str]) -> str:
    """
    Introducción global (2-4 frases) a partir de los títulos de sección. El LLM no
    re-emite contenido de secciones (el cosido es en código), así que no puede
    truncar el documento. Devuelve "" si falla: la intro es opcional.
    """
    if not section_titles:
        return ""
    listed = "\n".join(f"- {t}" for t in section_titles)
    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=INTRO_TEMPERATURE,
            max_tokens=INTRO_MAX_TOKENS,
            messages=[
                {"role": "system", "content": MEMORIA_INTRO_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Título de la licitación: '{licitacion_title}'\n\n"
                        f"SECCIONES DE LA MEMORIA (en orden):\n{listed}"
                    ),
                },
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning(f"Agente de introducción falló ('{licitacion_title}'): {e}", exc_info=True)
        return ""


# ── Normalización y cosido determinista ─────────────────────────────────────
# Los agentes pueden desviarse del formato pedido (fence envolviendo la prosa,
# encabezados de nivel 1, sección sin encabezado). El cosido corrige SOLO el
# envoltorio; el contenido de cada sección se preserva verbatim.

_FENCE = re.compile(r"^[ \t]*(?:```|~~~)[ \t]*([A-Za-z0-9_+-]*)[ \t]*$")
_TOP_HEADING = re.compile(r"^# (?=\S)", re.MULTILINE)
_SECTION_HEADING = re.compile(r"^\s{0,3}##\s")

# Info-strings de fence que delatan prosa envuelta por error (una memoria no
# contiene código: un fence sin lenguaje o markdown/md siempre es un error).
_PROSE_FENCE_LANGS = frozenset({"", "markdown", "md"})


def _unwrap_prose_fences(markdown: str) -> str:
    """
    Elimina fences que envuelven prosa (```/```markdown), incluso sin cerrar:
    renderizarían la sección como bloque de código. Los fences con lenguaje real
    se conservan intactos.
    """
    kept: list[str] = []
    dropping_fence = False   # dentro de un fence de prosa erróneo (se descartan sus delimitadores)
    inside_code = False      # dentro de un fence legítimo con lenguaje
    for line in markdown.split("\n"):
        match = _FENCE.match(line)
        if not match:
            kept.append(line)
            continue
        if inside_code:
            kept.append(line)
            inside_code = False
        elif dropping_fence:
            dropping_fence = False
        elif match.group(1).lower() in _PROSE_FENCE_LANGS:
            dropping_fence = True
        else:
            kept.append(line)
            inside_code = True
    return "\n".join(kept)


def _normalize_section_markdown(markdown: str, fallback_title: str) -> str:
    """
    Deja cada sección con el mismo envoltorio: sin fences espurios, encabezados de
    nivel 1 degradados a 2 (el «#» del documento lo pone el cosido) y garantía de
    que empieza por «## <título>».
    """
    md = (markdown or "").strip()
    if not md:
        return f"## {fallback_title}"
    md = _unwrap_prose_fences(md).strip()
    md = _TOP_HEADING.sub("## ", md)
    if not _SECTION_HEADING.match(md):
        md = f"## {fallback_title}\n\n{md}"
    return md


def _assemble_document(
    licitacion_title: str, intro: str, sections: list[tuple[str, str]]
) -> str:
    """
    Cosido DETERMINISTA del documento: «# título», intro opcional y secciones en
    orden, normalizadas pero con su contenido verbatim. Al no pasar por el LLM,
    el documento no puede truncarse.
    """
    blocks = [f"# {licitacion_title}"]
    if intro:
        blocks.append(intro)
    blocks.extend(
        _normalize_section_markdown(md, fallback_title) for fallback_title, md in sections
    )
    return "\n\n".join(blocks)


async def draft_propuesta(
    licitacion_id: str,
    user_id: str,
    title: str,
    esquema: list[MemoriaSectionDraft],
    db: Session,
    session_factory: Callable[[], Session] | None = None,
    tone: str = DEFAULT_TONE,
) -> MemoriaDocument:
    """
    Redacta la Memoria Técnica completa: fan-out de un agente por sección (en
    paralelo, acotado por semáforo) + introducción + cosido determinista en código.
    Persiste y devuelve el ``MemoriaDocument``.
    """
    started = time.monotonic()

    tone = normalize_tone(tone)
    profile_context = _default_profile_context(user_id, db)
    if profile_context.startswith("No hay perfil"):
        # spec-MP §5: poco material de empresa → el borrador saldrá lleno de
        # marcadores [COMPLETAR]. Se avisa en logs (la UI fija expectativas).
        logger.warning(
            f"Redacción de memoria sin perfil de empresa (licitación {licitacion_id}): "
            "el borrador marcará huecos [COMPLETAR] en todo lo relativo a la empresa."
        )
    requisitos = (
        db.query(PliegoRequirement)
        .filter(PliegoRequirement.licitacion_id == licitacion_id)
        .all()
    )

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — propuesta de memoria no disponible.")
        return _store_new_document(
            licitacion_id,
            user_id,
            "# Memoria Técnica\n\n_El servicio de redacción no está disponible en este momento._",
            db,
            session_factory,
        )

    ordered = sorted(esquema, key=lambda s: s.sort_order if s.sort_order is not None else 0)

    gate = asyncio.Semaphore(DRAFT_CONCURRENCY)
    drafted = await asyncio.gather(
        *(
            _draft_one_section(
                client, licitacion_id, user_id, title, section,
                requisitos, profile_context, tone, gate,
            )
            for section in ordered
        )
    )

    failed = sum(1 for md in drafted if SECTION_FAILURE_MARKER in md)
    if ordered and failed == len(ordered):
        raise RuntimeError(
            f"Los {failed} agentes de sección fallaron para la licitación {licitacion_id}; "
            "se aborta la propuesta."
        )

    intro = await _draft_intro(client, title, [s.title for s in ordered])
    markdown = _assemble_document(
        title, intro, [(s.title, md) for s, md in zip(ordered, drafted)]
    )
    doc = _store_new_document(licitacion_id, user_id, markdown, db, session_factory)

    logger.info(
        "Propuesta de memoria redactada",
        extra={
            "licitacion_id": licitacion_id,
            "doc_id": doc.id,
            "sections": len(ordered),
            "sections_failed": failed,
            "markdown_len": len(markdown),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": LLM_MODEL,
        },
    )
    return doc


# ═══════════════════════════════════════════════════════════════════════════
# Documentos (persistencia del Markdown)
# ═══════════════════════════════════════════════════════════════════════════

def get_documents(licitacion_id: str, user_id: str, db: Session) -> list[MemoriaDocument]:
    """Documentos de la licitación, el más reciente primero."""
    return (
        db.query(MemoriaDocument)
        .filter(
            MemoriaDocument.licitacion_id == licitacion_id,
            MemoriaDocument.user_id == user_id,
        )
        .order_by(MemoriaDocument.updated_at.desc())
        .all()
    )


def get_document_by_id(
    doc_id: str, licitacion_id: str, user_id: str, db: Session
) -> MemoriaDocument | None:
    return (
        db.query(MemoriaDocument)
        .filter(
            MemoriaDocument.id == doc_id,
            MemoriaDocument.licitacion_id == licitacion_id,
            MemoriaDocument.user_id == user_id,
        )
        .first()
    )


def _store_new_document(
    licitacion_id: str,
    user_id: str,
    markdown: str,
    db: Session,
    session_factory: Callable[[], Session] | None,
    title: str = "Borrador de Memoria",
) -> MemoriaDocument:
    """Persiste un documento nuevo (sesión fresca si hay ``session_factory``)."""
    now = datetime.now(timezone.utc)
    write_db = session_factory() if session_factory else db
    try:
        doc = MemoriaDocument(
            id=str(uuid.uuid4()),
            licitacion_id=licitacion_id,
            user_id=user_id,
            title=title,
            markdown=markdown,
            created_at=now,
            updated_at=now,
        )
        write_db.add(doc)
        write_db.commit()
        write_db.refresh(doc)
        return doc
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()


def update_document(
    doc_id: str,
    licitacion_id: str,
    user_id: str,
    title: str | None,
    markdown: str | None,
    db: Session,
    session_factory: Callable[[], Session] | None = None,
) -> MemoriaDocument | None:
    """Actualiza título y/o Markdown. ``None`` si el documento no es del usuario."""
    write_db = session_factory() if session_factory else db
    try:
        doc = (
            write_db.query(MemoriaDocument)
            .filter(
                MemoriaDocument.id == doc_id,
                MemoriaDocument.licitacion_id == licitacion_id,
                MemoriaDocument.user_id == user_id,
            )
            .first()
        )
        if doc is None:
            return None
        if title is not None:
            doc.title = title
        if markdown is not None:
            doc.markdown = markdown
        doc.updated_at = datetime.now(timezone.utc)
        write_db.commit()
        write_db.refresh(doc)
        return doc
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Fase 3 — chat de refinado sobre el Markdown
# ═══════════════════════════════════════════════════════════════════════════

def list_chat_history(
    licitacion_id: str,
    user_id: str,
    db: Session,
    doc_id: str | None = None,
) -> list[MemoriaChatMessage]:
    """Turnos del chat de refinado en orden cronológico (por documento si se pasa)."""
    q = db.query(MemoriaChatMessage).filter(
        MemoriaChatMessage.licitacion_id == licitacion_id,
        MemoriaChatMessage.user_id == user_id,
    )
    if doc_id is not None:
        q = q.filter(MemoriaChatMessage.doc_id == doc_id)
    return q.order_by(MemoriaChatMessage.created_at.asc()).all()


def _record_chat_turn(
    licitacion_id: str,
    user_id: str,
    doc_id: str,
    user_message: str,
    assistant_reply: str,
    db: Session,
    session_factory: Callable[[], Session] | None,
) -> None:
    """Guarda el par usuario→asistente. No propaga el fallo: perder un turno de
    histórico no debe romper la edición ya realizada (se loggea)."""
    write_db = session_factory() if session_factory else db
    try:
        write_db.add(
            MemoriaChatMessage(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                user_id=user_id,
                doc_id=doc_id,
                role="user",
                content=user_message,
                created_at=datetime.now(timezone.utc),
            )
        )
        write_db.add(
            MemoriaChatMessage(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                user_id=user_id,
                doc_id=doc_id,
                role="assistant",
                content=assistant_reply,
                # timestamp posterior → el orden user→assistant queda garantizado
                created_at=datetime.now(timezone.utc),
            )
        )
        write_db.commit()
    except Exception:
        write_db.rollback()
        logger.warning(
            f"No se pudo persistir el turno de chat de memoria ({licitacion_id})",
            exc_info=True,
        )
    finally:
        if write_db is not db:
            write_db.close()


async def refine_document(
    doc_id: str,
    licitacion_id: str,
    user_id: str,
    current_markdown: str,
    instruction: str,
    db: Session,
    session_factory: Callable[[], Session] | None = None,
) -> tuple[str, str]:
    """
    Aplica la petición del usuario sobre el Markdown vía LLM (con histórico del
    documento y grounding PPT + perfil). Persiste turno y documento.
    Devuelve ``(markdown_editado, mensaje_para_el_chat)``.
    """
    started = time.monotonic()

    history = list_chat_history(licitacion_id, user_id, db, doc_id=doc_id)[-REFINE_HISTORY_LIMIT:]
    ppt_chunks = await hybrid_search(
        "objeto del contrato, prestaciones, requisitos técnicos, alcance del servicio, "
        "entregables, niveles de servicio y plazos de ejecución",
        licitacion_id,
        user_id,
        top_k=REFINE_CONTEXT_TOP_K,
        document_type="ppt",
    )
    ppt_context = _chunks_as_text(ppt_chunks)
    profile_context = _default_profile_context(user_id, db)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — chat de memoria no disponible.")
        return current_markdown, "El servicio de edición no está disponible en este momento."

    messages: list[dict[str, str]] = [{"role": "system", "content": MEMORIA_REFINE_PROMPT}]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({
        "role": "user",
        "content": (
            f"DOCUMENTO ACTUAL (Markdown):\n{current_markdown}\n\n"
            f"CONTEXTO DEL PLIEGO:\n<fragmentos_pliego>\n"
            f"{ppt_context or 'No disponibles.'}\n</fragmentos_pliego>\n\n"
            f"CAPACIDADES REALES DE LA EMPRESA:\n<capacidades_empresa>\n"
            f"{profile_context}\n</capacidades_empresa>\n\n"
            f"PETICIÓN DEL USUARIO: {instruction}\n\n"
            "RECORDATORIO CRÍTICO: SOLO debes modificar lo que pide el usuario. "
            "El resto del documento debe permanecer EXACTAMENTE igual, carácter por "
            "carácter. No arregles estilo ni modifiques otras partes."
        ),
    })

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=REFINE_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=messages,
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido del LLM en chat de memoria de {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error en chat de memoria de {licitacion_id}: {e}", exc_info=True)
        raise

    edited = str(payload.get("markdown") or "").strip() or current_markdown
    reply = str(payload.get("texto_chat") or "").strip() or "Hecho."

    _record_chat_turn(licitacion_id, user_id, doc_id, instruction, reply, db, session_factory)
    update_document(doc_id, licitacion_id, user_id, None, edited, db, session_factory)

    logger.info(
        "Edición de memoria vía chat completada",
        extra={
            "licitacion_id": licitacion_id,
            "doc_id": doc_id,
            "history_turns": len(history),
            "markdown_len": len(edited),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": LLM_MODEL,
        },
    )
    return edited, reply


# ═══════════════════════════════════════════════════════════════════════════
# Fase 4 — revisión de coherencia del borrador completo (spec-MP §4)
# ═══════════════════════════════════════════════════════════════════════════

async def review_coherence(licitacion_id: str, markdown: str) -> list[dict[str, str]]:
    """
    Una llamada sobre el borrador COMPLETO tras la redacción: devuelve la lista de
    incidencias (contradicciones, repeticiones, requisitos sin cubrir, marcadores
    [COMPLETAR: …] pendientes, afirmaciones a verificar). NO reescribe: el humano
    decide qué corregir.
    """
    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — revisión de coherencia no disponible.")
        return []

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=COHERENCE_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": MEMORIA_COHERENCE_PROMPT},
                {"role": "user", "content": f"<borrador>\n{markdown}\n</borrador>"},
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido del LLM en coherencia de memoria de {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error en revisión de coherencia de {licitacion_id}: {e}", exc_info=True)
        raise

    raw = payload.get("incidencias", [])
    issues = [
        {
            "tipo": str(item.get("tipo") or "verificar"),
            "apartado": str(item.get("apartado") or ""),
            "detalle": str(item.get("detalle") or ""),
        }
        for item in raw
        if isinstance(item, dict) and (item.get("detalle") or item.get("apartado"))
    ]
    logger.info(
        "Revisión de coherencia completada",
        extra={"licitacion_id": licitacion_id, "incidencias": len(issues), "model": LLM_MODEL},
    )
    return issues

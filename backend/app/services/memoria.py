"""
Servicio de Memoria Técnica — reescrito desde spec funcional (DM5, spec-demo-minimal §2).

Contrato (síncrono, sin cola; el worker de 4.1 podrá invocar estas funciones tal cual
porque no dependen de la request: reciben ids + sesión de BD explícitos):

- ``propose_esquema(licitacion_id, user_id, title, user_message, db)``
    → ``MemoriaEsquemaResponse`` {reply, esquema[]}. Propone la estructura de secciones
      (no persiste). Grounding: criterios de adjudicación ya extraídos
      (``PliegoRequirement`` categoria='criterio_adjudicacion'); fallback búsqueda
      híbrida sobre el PCAP. Contexto adicional: títulos recurrentes de memorias
      previas del usuario y secciones ya guardadas.
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

from sqlalchemy import func
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
    MEMORIA_CHAT_PROMPT,
    MEMORIA_ESQUEMA_PROMPT,
    MEMORIA_INTRO_PROMPT,
    MEMORIA_SECTION_PROMPT,
)
from app.services.embeddings import get_openai_client
from app.services.match import build_profile_text
from app.services.query import hybrid_search

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"

# Temperaturas por tarea (CLAUDE.md §8: 0.2 extractivo, más alta solo en redacción).
ESQUEMA_TEMPERATURE = 0.2
DRAFT_TEMPERATURE = 0.5
REFINE_TEMPERATURE = 0.2
INTRO_TEMPERATURE = 0.3
INTRO_MAX_TOKENS = 400

# Nº máximo de agentes de sección simultáneos (cuota TPM/RPM de Azure OpenAI).
DRAFT_CONCURRENCY = 5
# Chunks del PPT por sección (retrieval específico del apartado).
SECTION_EVIDENCE_TOP_K = 8
# Chunks del PCAP para el fallback de criterios del esquema.
CRITERIOS_FALLBACK_TOP_K = 8
# Chunks del PPT para el contexto global del chat de refinado.
REFINE_CONTEXT_TOP_K = 20
# Requisitos máximos inyectados a cada agente de sección.
SECTION_MAX_REQUISITOS = 6
# Títulos recurrentes de memorias previas que se ofrecen como plantilla implícita.
RECURRING_TITLES_LIMIT = 12
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


def recurring_titles(user_id: str, exclude_licitacion_id: str, db: Session) -> list[str]:
    """
    Títulos de sección que se repiten en memorias `accepted` previas del usuario
    (plantilla implícita), ordenados por frecuencia. Excluye la licitación actual
    y respeta el aislamiento por user_id (§10).
    """
    normalized = func.lower(func.trim(MemoriaSection.title))
    rows = (
        db.query(MemoriaSection.title, func.count().label("freq"))
        .filter(
            MemoriaSection.user_id == user_id,
            MemoriaSection.licitacion_id != exclude_licitacion_id,
            MemoriaSection.status == "accepted",
        )
        .group_by(normalized, MemoriaSection.title)
        .order_by(func.count().desc())
        .limit(RECURRING_TITLES_LIMIT)
        .all()
    )
    seen: set[str] = set()
    titles: list[str] = []
    for title, _freq in rows:
        key = " ".join((title or "").lower().split())
        if key and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


# ═══════════════════════════════════════════════════════════════════════════
# Fase 1 — esquema (propuesta de estructura, no persiste)
# ═══════════════════════════════════════════════════════════════════════════

async def _criterios_context(licitacion_id: str, user_id: str, db: Session) -> str:
    """
    Criterios de adjudicación como texto de grounding. Primero los ya extraídos
    (requisitos categoria='criterio_adjudicacion'); si no hay, búsqueda híbrida
    sobre el PCAP.
    """
    extracted = (
        db.query(PliegoRequirement)
        .filter(
            PliegoRequirement.licitacion_id == licitacion_id,
            PliegoRequirement.categoria == "criterio_adjudicacion",
        )
        .all()
    )
    if extracted:
        return "\n".join(
            f"- {r.descripcion}" + (f" [p. {r.pagina}]" if r.pagina else "")
            for r in extracted
        )

    chunks = await hybrid_search(
        "criterios de adjudicación, juicio de valor, puntuación de la memoria técnica",
        licitacion_id,
        user_id,
        top_k=CRITERIOS_FALLBACK_TOP_K,
        document_type="pcap",
    )
    return _chunks_as_text(chunks)


def _chunks_as_text(chunks: list[dict[str, Any]]) -> str:
    """Chunks → bloque de texto con etiqueta de página, en orden de lectura."""
    if not chunks:
        return ""
    ordered = sorted(chunks, key=lambda c: c.get("page_number") or 0)
    return "\n\n".join(
        f"[p. {c.get('page_number', '?')}] {c['text']}" for c in ordered
    )


def _esquema_user_message(
    title: str,
    user_message: str,
    criterios: str,
    previous_titles: list[str],
    existing: list[MemoriaSectionResponse],
) -> str:
    blocks = [f"Licitación: '{title}'", f"\nMensaje del usuario: {user_message}"]
    if criterios:
        blocks.append(f"\nCRITERIOS DE ADJUDICACIÓN del pliego:\n{criterios}")
    else:
        blocks.append(
            "\nCRITERIOS DE ADJUDICACIÓN: no disponibles. Si te faltan datos, "
            "pregunta al usuario en 'reply'."
        )
    if previous_titles:
        listed = "\n".join(f"- {t}" for t in previous_titles)
        blocks.append(f"\nPLANTILLA (secciones de memorias previas del usuario):\n{listed}")
    if existing:
        listed = "\n".join(f"- {s.title}" for s in existing)
        blocks.append(f"\nSECCIONES EXISTENTES (refínalas, no las dupliques):\n{listed}")
    return "\n".join(blocks)


def _drafts_from_llm(raw: list[Any]) -> list[MemoriaSectionDraft]:
    """Salida del LLM → drafts validados (descarta entradas sin título)."""
    drafts: list[MemoriaSectionDraft] = []
    for position, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        drafts.append(
            MemoriaSectionDraft(
                title=title,
                description=item.get("description"),
                criterio_adjudicacion=item.get("criterio_adjudicacion"),
                max_puntos=item.get("max_puntos"),
                page_budget=item.get("page_budget"),
                sort_order=item.get("sort_order", position),
            )
        )
    return drafts


async def propose_esquema(
    licitacion_id: str,
    user_id: str,
    title: str,
    user_message: str,
    db: Session,
) -> MemoriaEsquemaResponse:
    """Propone la estructura de la memoria (sin persistir). Ver docstring de módulo."""
    started = time.monotonic()

    existing = get_sections(licitacion_id, user_id, db)
    previous_titles = recurring_titles(user_id, licitacion_id, db)
    criterios = await _criterios_context(licitacion_id, user_id, db)

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — esquema de memoria no disponible.")
        return MemoriaEsquemaResponse(
            reply="El servicio de propuesta de secciones no está disponible en este momento.",
            esquema=[],
        )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=ESQUEMA_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": MEMORIA_ESQUEMA_PROMPT},
                {
                    "role": "user",
                    "content": _esquema_user_message(
                        title, user_message, criterios, previous_titles, existing
                    ),
                },
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido del LLM en esquema de memoria de {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error proponiendo esquema de memoria de {licitacion_id}: {e}", exc_info=True)
        raise

    esquema = _drafts_from_llm(payload.get("secciones", []))
    reply = str(payload.get("reply") or "").strip() or "He propuesto una estructura de secciones."

    logger.info(
        "Esquema de memoria propuesto",
        extra={
            "licitacion_id": licitacion_id,
            "esquema_count": len(esquema),
            "has_criterios": bool(criterios),
            "existing_count": len(existing),
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


async def _draft_one_section(
    client: Any,
    licitacion_id: str,
    user_id: str,
    licitacion_title: str,
    section: MemoriaSectionDraft,
    requisitos: list[PliegoRequirement],
    profile_context: str,
    gate: asyncio.Semaphore,
) -> str:
    """
    Redacta el Markdown de UNA sección (evidencia del PPT + requisitos afines +
    perfil). Si el LLM falla, devuelve la sección degradada con marcador: la
    propuesta completa nunca aborta por una sección.
    """
    async with gate:
        evidence_chunks = await hybrid_search(
            _section_topic(section) or section.title,
            licitacion_id,
            user_id,
            top_k=SECTION_EVIDENCE_TOP_K,
            document_type="ppt",
        )
        evidence = _chunks_as_text(evidence_chunks)
        requisitos_block = _assign_requisitos(section, requisitos)

        header = [f"Título de la sección: {section.title}"]
        if section.description:
            header.append(f"Qué debe cubrir: {section.description}")
        if section.criterio_adjudicacion:
            header.append(f"Criterio de adjudicación al que responde: {section.criterio_adjudicacion}")
        if section.max_puntos is not None:
            header.append(f"Puntos del criterio: {section.max_puntos}")
        if section.page_budget is not None:
            header.append(f"Extensión recomendada: {section.page_budget} páginas")

        user_message = "\n".join([
            f"Licitación: '{licitacion_title}'",
            "\nSECCIÓN A REDACTAR:\n" + "\n".join(header),
            f"\nEVIDENCIA DEL PPT (relevante para esta sección):\n{evidence or 'No disponible.'}",
            f"\nREQUISITOS RELEVANTES:\n{requisitos_block or 'No disponibles.'}",
            f"\nPERFIL DE LA EMPRESA:\n{profile_context}",
        ])

        try:
            response = await client.chat.completions.create(
                model=LLM_MODEL,
                temperature=DRAFT_TEMPERATURE,
                messages=[
                    {"role": "system", "content": MEMORIA_SECTION_PROMPT},
                    {"role": "user", "content": user_message},
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
) -> MemoriaDocument:
    """
    Redacta la Memoria Técnica completa: fan-out de un agente por sección (en
    paralelo, acotado por semáforo) + introducción + cosido determinista en código.
    Persiste y devuelve el ``MemoriaDocument``.
    """
    started = time.monotonic()

    profile_context = _default_profile_context(user_id, db)
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
                requisitos, profile_context, gate,
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

    messages: list[dict[str, str]] = [{"role": "system", "content": MEMORIA_CHAT_PROMPT}]
    messages.extend({"role": m.role, "content": m.content} for m in history)
    messages.append({
        "role": "user",
        "content": (
            f"DOCUMENTO ACTUAL (Markdown):\n{current_markdown}\n\n"
            f"FRAGMENTOS DEL PPT:\n{ppt_context or 'No disponibles.'}\n\n"
            f"PERFIL DE LA EMPRESA:\n{profile_context}\n\n"
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

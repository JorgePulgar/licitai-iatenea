"""
Extracción de requisitos del pliego — reescrito desde spec funcional (tarea 5.5 / DM4).

Contrato:
- ``extract_requirements(...)`` → RequirementsListResponse. Cache-first sobre
  ``pliego_requirements``; en frío: retrieval multi-query EN PARALELO
  (``asyncio.gather`` acotado por semáforo, ~18 búsquedas secuenciales antes),
  LLM (REQUIREMENTS_SYSTEM_PROMPT v1.0, JSON, chunks fenceados en <fragmentos>),
  validación de salida (enum de categoría, páginas contra los page_counts reales,
  dedup por descripción normalizada) y persistencia con sesión fresca.
- ``invalidate_requirements(licitacion_id, db)`` → nº de filas borradas. Lo usan
  el endpoint de regeneración y el reindexado (los requisitos cacheados quedan
  obsoletos cuando cambian los documentos).
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.domain import PliegoRequirement
from app.models.schemas import RequirementResponse, RequirementsListResponse
from app.prompts.requirements import REQUIREMENTS_SYSTEM_PROMPT
from app.services.embeddings import get_openai_client
from app.services.query import hybrid_search

logger = get_logger(__name__)

LLM_MODEL = "extraccion_datos_4o"
LLM_TEMPERATURE = 0.2

RETRIEVAL_TOP_K = 15

# Búsquedas simultáneas máximas contra AI Search/embeddings (cuota TPM/RPM de Azure;
# mismo criterio que el fan-out de memoria).
SEARCH_CONCURRENCY = 6

VALID_CATEGORIES = frozenset({"administrativo", "tecnico", "economico", "plazo"})
VALID_DOC_TYPES = frozenset({"pcap", "ppt", "anexo"})
_FALLBACK_CATEGORY = "tecnico"
_FALLBACK_DOC_TYPE = "pcap"

# Consultas de cobertura: una por familia de requisitos, formuladas como pregunta
# para maximizar el match semántico con contenido sustantivo (no índices).
_COVERAGE_QUERIES = [
    # Administrativo
    "¿Qué documentación administrativa debe presentar el licitador y en qué plazo?",
    "¿Qué garantía definitiva o provisional se exige y qué porcentaje representa?",
    "¿Se exige clasificación empresarial (grupo, subgrupo, categoría)?",
    "¿Está permitida la subcontratación o la concurrencia en UTE y con qué condiciones?",
    # Solvencia técnica
    "¿Qué experiencia previa en contratos de objeto similar se exige acreditar?",
    "¿Qué composición mínima del equipo de trabajo se exige (perfiles, titulaciones)?",
    "¿Qué certificados o normas son de obligado cumplimiento (ISO, ENS, seguridad)?",
    "¿Qué medios materiales, instalaciones o infraestructura debe aportar el adjudicatario?",
    # Solvencia económica
    "¿Qué volumen anual de negocio mínimo y qué seguros se exigen al licitador?",
    # Técnico / PPT
    "¿Qué prestaciones y trabajos concretos componen el objeto del contrato?",
    "¿Qué acuerdos de nivel de servicio, disponibilidad o tiempos de respuesta se exigen?",
    "¿Qué penalidades se aplican por incumplimiento y cómo se calculan?",
    "¿Qué entregables, informes o documentación debe producir el adjudicatario?",
    "¿Cuál es el plazo de ejecución y qué hitos o fases contempla?",
    # Criterios de adjudicación y económicos
    "¿Cómo se puntúan las ofertas: criterios de adjudicación y ponderaciones?",
    "¿Qué criterios dependen de juicio de valor (memoria técnica, metodología)?",
    "¿Cuál es la fórmula de valoración de la oferta económica?",
    "¿Cuál es el presupuesto base de licitación y el valor estimado del contrato?",
]


async def extract_requirements(
    licitacion_id: str,
    user_id: str,
    title: str,
    db: Session,
    session_factory: Callable[[], Session] | None = None,
    page_counts: dict[str, int] | None = None,
) -> RequirementsListResponse:
    """Extrae y persiste los requisitos de la licitación (cache-first).

    ``db`` se usa solo para leer la cache; la escritura abre una sesión fresca de
    ``session_factory`` porque la conexión original puede caducar durante el
    retrieval + LLM (minutos, SQL Server corta el TCP). ``page_counts`` mapea
    document_type→nº de páginas reales y permite descartar citas de página
    imposibles (confianza en citas, claude.md §8).
    """
    cached = (
        db.query(PliegoRequirement)
        .filter(PliegoRequirement.licitacion_id == licitacion_id)
        .all()
    )
    if cached:
        return RequirementsListResponse(
            licitacion_id=licitacion_id,
            requirements=[_to_response(r) for r in cached],
            cached=True,
            generated_at=cached[0].generated_at,
        )

    chunks = await _retrieve_coverage_chunks(licitacion_id, user_id)
    if not chunks:
        logger.warning(f"Sin chunks para requisitos de la licitación {licitacion_id}.")
        return RequirementsListResponse(
            licitacion_id=licitacion_id, requirements=[], cached=False
        )

    raw_items = await _ask_llm(chunks, title, licitacion_id)

    now = datetime.now(timezone.utc)
    records = _validate_and_dedup(raw_items, licitacion_id, page_counts or {}, now)
    # Las respuestas se construyen ANTES de persistir: tras el commit los objetos
    # quedan expirados y desligados de la sesión fresca (que se cierra).
    responses = [_to_response(r) for r in records]

    _persist(records, db, session_factory)

    logger.info(
        f"Requisitos extraídos para {licitacion_id}: "
        f"{len(raw_items)} crudos → {len(records)} únicos y validados."
    )
    return RequirementsListResponse(
        licitacion_id=licitacion_id,
        requirements=responses,
        cached=False,
        generated_at=now,
    )


def invalidate_requirements(licitacion_id: str, db: Session) -> int:
    """Borra la cache de requisitos (regeneración manual o cambio de documentos)."""
    deleted = (
        db.query(PliegoRequirement)
        .filter(PliegoRequirement.licitacion_id == licitacion_id)
        .delete()
    )
    db.commit()
    if deleted:
        logger.info(f"Cache de requisitos invalidada para {licitacion_id}: {deleted} filas.")
    return deleted


# ── Retrieval ────────────────────────────────────────────────────────────────


async def _retrieve_coverage_chunks(
    licitacion_id: str, user_id: str
) -> list[dict[str, Any]]:
    """Lanza las consultas de cobertura en paralelo y deduplica los chunks.

    Antes: ~18 búsquedas secuenciales (una espera de red tras otra). Ahora:
    ``asyncio.gather`` acotado por semáforo → latencia ≈ la de la búsqueda más
    lenta por ola (aceptación 5.5: ≤ ~1/10 de la latencia anterior).
    """
    semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

    async def bounded_search(query: str) -> list[dict[str, Any]]:
        async with semaphore:
            return await hybrid_search(
                query, licitacion_id, user_id, top_k=RETRIEVAL_TOP_K
            )

    results = await asyncio.gather(
        *(bounded_search(q) for q in _COVERAGE_QUERIES)
    )

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for batch in results:
        for chunk in batch:
            key = chunk.get("chunk_id") or chunk.get("text", "")[:80]
            if key not in seen:
                seen.add(key)
                unique.append(chunk)

    # Orden de lectura (documento, página) para un contexto coherente.
    unique.sort(key=lambda c: (c.get("document_type", ""), c.get("page_number") or 0))
    return unique


# ── LLM ──────────────────────────────────────────────────────────────────────


async def _ask_llm(
    chunks: list[dict[str, Any]], title: str, licitacion_id: str
) -> list[dict[str, Any]]:
    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no configurado — extracción de requisitos no disponible.")
        return []

    context = "\n\n".join(
        f"[{c.get('document_type', '')} p. {c.get('page_number', '?')}] {c['text']}"
        for c in chunks
    )
    # Fencing anti-inyección (1.8): los chunks son texto no confiable.
    user_message = (
        f"Licitación: '{title}'\n\n<fragmentos>\n{context}\n</fragmentos>"
    )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": REQUIREMENTS_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        logger.info(
            "Respuesta LLM de requisitos recibida",
            extra={
                "licitacion_id": licitacion_id,
                "context_chars": len(context),
                "finish_reason": response.choices[0].finish_reason,
            },
        )
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido del LLM en requisitos de {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error extrayendo requisitos de {licitacion_id}: {e}")
        raise

    items = data.get("requisitos", [])
    return items if isinstance(items, list) else []


# ── Validación y persistencia ────────────────────────────────────────────────


def _validate_and_dedup(
    raw_items: list[dict[str, Any]],
    licitacion_id: str,
    page_counts: dict[str, int],
    now: datetime,
) -> list[PliegoRequirement]:
    """Aplica el contrato de salida: enum de categoría/documento, página verificada
    contra el nº real de páginas del documento origen, dedup por descripción."""
    seen_descriptions: set[str] = set()
    records: list[PliegoRequirement] = []

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("descripcion") or "").strip()
        dedup_key = " ".join(description.lower().split())
        if not dedup_key or dedup_key in seen_descriptions:
            continue
        seen_descriptions.add(dedup_key)

        category = str(item.get("categoria") or "").strip().lower()
        if category not in VALID_CATEGORIES:
            logger.warning(
                f"Categoría fuera de enum ('{category}') en {licitacion_id}; "
                f"se normaliza a '{_FALLBACK_CATEGORY}'."
            )
            category = _FALLBACK_CATEGORY

        doc_type = str(item.get("documento_origen") or "").strip().lower()
        if doc_type not in VALID_DOC_TYPES:
            doc_type = _FALLBACK_DOC_TYPE

        records.append(
            PliegoRequirement(
                id=str(uuid.uuid4()),
                licitacion_id=licitacion_id,
                categoria=category,
                descripcion=description,
                pagina=_validated_page(item.get("pagina"), doc_type, page_counts, licitacion_id),
                documento_origen=doc_type,
                es_obligatorio=bool(item.get("es_obligatorio", True)),
                generated_at=now,
            )
        )
    return records


def _validated_page(
    raw_page: Any,
    doc_type: str,
    page_counts: dict[str, int],
    licitacion_id: str,
) -> int | None:
    """Página citada → None si no es un entero positivo o excede las páginas reales
    del documento origen. Mejor sin cita que con una cita falsa (claude.md §8)."""
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        return None
    if page < 1:
        return None
    max_pages = page_counts.get(doc_type)
    if max_pages is not None and page > max_pages:
        logger.warning(
            f"Página citada imposible en {licitacion_id}: {doc_type} p. {page} "
            f"(el documento tiene {max_pages}); se descarta la cita."
        )
        return None
    return page


def _persist(
    records: list[PliegoRequirement],
    db: Session,
    session_factory: Callable[[], Session] | None,
) -> None:
    """Escribe con sesión fresca: la original lleva minutos ociosa (búsqueda + LLM)
    y SQL Server puede haber cortado la conexión."""
    write_db = session_factory() if session_factory else db
    try:
        write_db.add_all(records)
        write_db.commit()
    except Exception:
        write_db.rollback()
        raise
    finally:
        if write_db is not db:
            write_db.close()


def _to_response(record: PliegoRequirement) -> RequirementResponse:
    return RequirementResponse(
        id=record.id,
        categoria=record.categoria,
        descripcion=record.descripcion,
        pagina=record.pagina,
        documento_origen=record.documento_origen,
        es_obligatorio=record.es_obligatorio,
    )

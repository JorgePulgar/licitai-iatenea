import re
import time
import uuid
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, RetryError

from app.core.config import settings
from app.core.logging import get_logger, set_log_context
from app.models.schemas import Citation, QueryResponse
from app.prompts.query import QUERY_SYSTEM_PROMPT
from app.services.embeddings import embed_text, get_openai_client

logger = get_logger(__name__)

OPENAI_MAX_RETRIES = 3

TOP_K = 8
LLM_MODEL = "chat_pliego_4o"
LLM_TEMPERATURE = 0.2

# Expansión por vecinos: por cada chunk recuperado se añaden al contexto sus vecinos
# de lectura (seq±RADIUS) del mismo pliego. Cubre respuestas partidas entre el chunk
# que hizo match y el contiguo. Los vecinos entran SOLO como contexto del LLM; no
# alteran el ranking. TOP_K se baja a 8 para que (hits + vecinos + historial) quepan
# en el contexto. Los chunks heredados sin `seq` se ignoran con elegancia.
ENABLE_NEIGHBOR_EXPANSION = True
NEIGHBOR_RADIUS = 1


def _get_search_client() -> SearchClient | None:
    if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
        return None
    return SearchClient(
        endpoint=settings.AZURE_SEARCH_ENDPOINT,
        index_name=settings.AZURE_SEARCH_INDEX_NAME,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
    )


async def hybrid_search(
    query: str,
    licitacion_id: str,
    user_id: str,
    top_k: int = TOP_K,
    document_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Hybrid keyword + vector search with semantic reranker.
    Always filters by licitacion_id and user_id.
    Optionally filters by document_type (pcap | ppt | anexo).
    """
    client = _get_search_client()
    if not client:
        logger.warning("Azure AI Search not configured — hybrid search unavailable.")
        return []

    query_vector = await embed_text(query)

    vector_queries = []
    if query_vector:
        vector_queries.append(
            VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k,
                fields="embedding",
            )
        )

    try:
        lid = licitacion_id.lower()
        uid = user_id.lower()
        filter_parts = [f"licitacion_id eq '{lid}'", f"user_id eq '{uid}'"]
        if document_type:
            filter_parts.append(f"document_type eq '{document_type}'")
        filter_str = " and ".join(filter_parts)

        results = client.search(
            search_text=query,
            vector_queries=vector_queries,
            filter=filter_str,
            query_type="semantic",
            semantic_configuration_name="licitai-semantic-config",
            top=top_k,
            select=["id", "chunk_id", "pliego_id", "licitacion_id", "document_type", "filename", "text", "section_heading", "page_number", "seq"],
        )

        chunks = []
        for r in results:
            chunks.append({
                "chunk_id": r.get("chunk_id"),
                "pliego_id": r.get("pliego_id"),
                "licitacion_id": r.get("licitacion_id"),
                "document_type": r.get("document_type", ""),
                "filename": r.get("filename", ""),
                "text": r.get("text", ""),
                "section_heading": r.get("section_heading", ""),
                "page_number": r.get("page_number"),
                "seq": r.get("seq"),
                "score": r.get("@search.reranker_score") or r.get("@search.score", 0.0),
            })

        logger.info(
            "Hybrid search completed",
            extra={"licitacion_id": licitacion_id, "chunks_retrieved": len(chunks)},
        )
        return chunks

    except Exception as e:
        logger.error(f"Hybrid search error for licitacion {licitacion_id}: {e}")
        return []


def _escape_odata(value: str) -> str:
    """Escapa comillas simples para literales de filtro OData (AI Search)."""
    return value.replace("'", "''")


async def _expand_neighbors(
    chunks: list[dict[str, Any]],
    licitacion_id: str,
    user_id: str,
    radius: int = NEIGHBOR_RADIUS,
) -> list[dict[str, Any]]:
    """Añade los vecinos de lectura (seq±radius) de cada chunk recuperado.

    Una respuesta puede quedar partida entre el chunk que hizo match y el contiguo;
    traer los vecinos al contexto la completa. Mantiene el aislamiento (filtra por
    licitacion_id + user_id) e ignora chunks sin `seq` (heredados). Los vecinos llevan
    score 0 — son contexto, no compiten en el ranking. Devuelve la lista combinada
    ordenada en orden de lectura (pliego_id, seq).
    """
    client = _get_search_client()
    if not client or radius < 1:
        return chunks

    existing_ids = {c.get("chunk_id") for c in chunks}
    # seq objetivo por pliego (excluyendo los seq ya presentes y negativos).
    wanted: dict[str, set[int]] = {}
    have_seq: dict[str, set[int]] = {}
    for c in chunks:
        seq = c.get("seq")
        pid = c.get("pliego_id")
        if seq is None or pid is None:
            continue
        have_seq.setdefault(pid, set()).add(seq)
    for c in chunks:
        seq = c.get("seq")
        pid = c.get("pliego_id")
        if seq is None or pid is None:
            continue
        for delta in range(-radius, radius + 1):
            if delta == 0:
                continue
            n = seq + delta
            if n >= 0 and n not in have_seq.get(pid, set()):
                wanted.setdefault(pid, set()).add(n)

    if not wanted:
        return chunks

    lid = _escape_odata(licitacion_id.lower())
    uid = _escape_odata(user_id.lower())
    clauses = []
    total_wanted = 0
    for pid, seqs in wanted.items():
        seq_clause = " or ".join(f"seq eq {s}" for s in sorted(seqs))
        clauses.append(f"(pliego_id eq '{_escape_odata(pid)}' and ({seq_clause}))")
        total_wanted += len(seqs)
    neighbor_filter = (
        f"licitacion_id eq '{lid}' and user_id eq '{uid}' and ({' or '.join(clauses)})"
    )

    try:
        results = client.search(
            search_text="*",
            filter=neighbor_filter,
            top=total_wanted,
            select=["chunk_id", "pliego_id", "licitacion_id", "document_type",
                    "filename", "text", "section_heading", "page_number", "seq"],
        )
        added = 0
        for r in results:
            if r.get("chunk_id") in existing_ids:
                continue
            chunks.append({
                "chunk_id": r.get("chunk_id"),
                "pliego_id": r.get("pliego_id"),
                "licitacion_id": r.get("licitacion_id"),
                "document_type": r.get("document_type", ""),
                "filename": r.get("filename", ""),
                "text": r.get("text", ""),
                "section_heading": r.get("section_heading", ""),
                "page_number": r.get("page_number"),
                "seq": r.get("seq"),
                "score": 0.0,
            })
            existing_ids.add(r.get("chunk_id"))
            added += 1
        logger.info(
            "Neighbor expansion completed",
            extra={"licitacion_id": licitacion_id, "neighbors_added": added},
        )
    except Exception as e:
        logger.error(f"Neighbor expansion error for licitacion {licitacion_id}: {e}")
        return chunks

    # Orden de lectura: agrupa cada hit con sus vecinos. seq None al final.
    chunks.sort(key=lambda c: (
        c.get("pliego_id") or "",
        c.get("seq") if c.get("seq") is not None else 1 << 30,
    ))
    return chunks


# Matches inline citation markers in the LLM answer: [pcap p. 5] or bare [p. 5].
# The doc-type tag is optional so a stray untagged marker doesn't blank a good answer.
_CITE_RE = re.compile(r"\[(?:(\w+)\s+)?p\.\s*(\d+)\]", re.IGNORECASE)


def _select_cited_chunks(
    answer: str, chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep only chunks the answer cites via [doc p. N] / [p. N].

    No markers -> no citations (forces prompt compliance, per design decision).
    Dedups to one chunk per (pliego_id, page); highest score wins. A bare
    [p. N] (no doc-type tag) matches any document_type on that page.
    """
    cited_typed: set[tuple[str, int]] = set()
    cited_pages: set[int] = set()
    for dt, page in _CITE_RE.findall(answer):
        if dt:
            cited_typed.add((dt.lower(), int(page)))
        else:
            cited_pages.add(int(page))

    if not cited_typed and not cited_pages:
        return []

    best: dict[tuple[str, int], dict[str, Any]] = {}
    for c in chunks:
        page = c.get("page_number")
        if page is None:
            continue
        dt = (c.get("document_type") or "").lower()
        if (dt, page) in cited_typed or page in cited_pages:
            key = (c.get("pliego_id", ""), page)
            if key not in best or c.get("score", 0) > best[key].get("score", 0):
                best[key] = c
    return list(best.values())


def _build_context(chunks: list[dict[str, Any]]) -> str:
    lines = []
    for c in chunks:
        page = c.get("page_number")
        doc_type = c.get("document_type", "")
        prefix = f"[{doc_type} p. {page}]" if page else f"[{doc_type} p. ?]"
        lines.append(f"{prefix} {c['text']}")
    return "\n\n".join(lines)


_NO_INFO_ANSWER = (
    "No he encontrado información sobre esto en el pliego. "
    "Prueba con otra formulación."
)

# Markers the LLM inserts when it cannot answer from the provided fragments.
# Kept in sync with the system prompt (QUERY_SYSTEM_PROMPT).
_LLM_NO_INFO_MARKERS = [
    "no se encuentra en el pliego",
    "no aparece en los fragmentos",
    "no he encontrado información",
    "no dispongo de información",
    "no encuentro información",
    "no está disponible en el pliego",
]


def _is_unanswerable(answer: str) -> bool:
    """Returns True when the LLM answer signals it found no relevant information."""
    lower = answer.lower()
    return any(marker in lower for marker in _LLM_NO_INFO_MARKERS)


async def generate_answer(
    question: str,
    chunks: list[dict[str, Any]],
    licitacion_id: str,
    title: str,
    history: list[tuple[str, str]] | None = None,
) -> QueryResponse:
    # Sin fragmentos Y sin conversación previa no hay nada que responder (pregunta fría
    # de pliego sin evidencia). Pero si hay historial, dejamos pasar al LLM: puede ser un
    # turno conversacional ("¿qué te acabo de decir?", saludo) que se resuelve con la
    # conversación, no con el pliego.
    if not chunks and not history:
        return QueryResponse(
            answer=_NO_INFO_ANSWER,
            citations=[],
        )

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — cannot generate answer.")
        return QueryResponse(
            answer="El servicio de generación de respuestas no está disponible en este momento.",
            citations=[],
        )

    context = _build_context(chunks)
    # Fencing anti-inyección (1.8): los chunks son texto no confiable; el prompt v2.0
    # instruye a tratar todo lo que haya dentro de <fragmentos> como datos, no órdenes.
    user_message = (
        f"Pregunta: {question}\n\n"
        f"<fragmentos>\n{context}\n</fragmentos>"
    )
    # Intercala los turnos previos (pregunta del usuario + respuesta del asistente) entre
    # el system prompt y la pregunta actual, para que el LLM mantenga el hilo de la
    # conversación (preguntas de seguimiento del tipo "¿y eso cuánto cuesta?").
    messages: list[dict[str, str]] = [{"role": "system", "content": QUERY_SYSTEM_PROMPT}]
    for past_question, past_answer in history or []:
        messages.append({"role": "user", "content": past_question})
        messages.append({"role": "assistant", "content": past_answer})
    messages.append({"role": "user", "content": user_message})

    @retry(
        stop=stop_after_attempt(OPENAI_MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=False,
    )
    async def _call_llm():
        return await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            messages=messages,
        )

    try:
        response = await _call_llm()
        answer = response.choices[0].message.content or ""
        # Telemetría de uso (tarea 1.7): se propaga en el QueryResponse (campos
        # exclude=True, nunca serializados) para que el endpoint la persista.
        usage = getattr(response, "usage", None)
        tokens_prompt = getattr(usage, "prompt_tokens", None)
        tokens_completion = getattr(usage, "completion_tokens", None)
        if _is_unanswerable(answer):
            logger.info(
                f"LLM signalled no relevant info for licitacion {licitacion_id}. "
                "Returning standard no-info response."
            )
            return QueryResponse(
                answer=_NO_INFO_ANSWER,
                citations=[],
                tokens_prompt=tokens_prompt,
                tokens_completion=tokens_completion,
            )
    except RetryError as e:
        # exc_info=True → se registra como excepción en App Insights (LIC-101/103).
        logger.error(
            f"OpenAI LLM unavailable after {OPENAI_MAX_RETRIES} retries for licitacion {licitacion_id}: {e}",
            exc_info=True,
        )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Servicio temporalmente no disponible. Inténtalo de nuevo en unos momentos.",
        )
    except Exception as e:
        logger.error(f"LLM error for licitacion {licitacion_id}: {e}", exc_info=True)
        raise

    cited_chunks = _select_cited_chunks(answer, chunks)
    citations = [
        Citation(
            content=c["text"],
            page_number=c.get("page_number"),
            pliego_id=c.get("pliego_id", ""),
            licitacion_id=licitacion_id,
            filename=c.get("filename", ""),
            document_type=c.get("document_type", ""),
        )
        for c in cited_chunks
    ]

    return QueryResponse(
        answer=answer,
        citations=citations,
        tokens_prompt=tokens_prompt,
        tokens_completion=tokens_completion,
    )


def validate_citations(
    citations: list[Citation],
    page_counts: dict[str, int],
) -> list[Citation]:
    """Removes citations whose page_number exceeds the known page count for that pliego."""
    valid = []
    for c in citations:
        max_pages = page_counts.get(c.pliego_id)
        if max_pages is None:
            valid.append(c)
            continue
        if c.page_number is not None and c.page_number > max_pages:
            logger.warning(
                f"Citation filtered: pliego {c.pliego_id} page {c.page_number} "
                f"exceeds document length ({max_pages} pages)."
            )
            continue
        valid.append(c)
    return valid


async def query_licitacion(
    question: str,
    licitacion_id: str,
    user_id: str,
    title: str,
    document_type: str | None = None,
    page_counts: dict[str, int] | None = None,
    history: list[tuple[str, str]] | None = None,
) -> QueryResponse:
    """Full RAG pipeline: hybrid search → LLM answer with inline citations.

    ``history`` son los turnos previos (pregunta, respuesta) de la misma licitación;
    se reinyectan al LLM para que las preguntas de seguimiento tengan contexto.
    """
    query_id = str(uuid.uuid4())
    set_log_context(pliego_id=licitacion_id)
    t_start = time.monotonic()

    logger.info(
        "RAG query started",
        extra={"query_id": query_id, "licitacion_id": licitacion_id, "question": question},
    )

    chunks = await hybrid_search(question, licitacion_id, user_id, document_type=document_type)

    if ENABLE_NEIGHBOR_EXPANSION:
        chunks = await _expand_neighbors(chunks, licitacion_id, user_id)

    # Log chunk IDs and scores — never log chunk text (may contain sensitive content)
    logger.info(
        "Chunks retrieved",
        extra={
            "query_id": query_id,
            "chunks_retrieved": len(chunks),
            "chunk_ids_scores": [
                {"chunk_id": c.get("chunk_id"), "score": round(c.get("score", 0.0), 4)}
                for c in chunks
            ],
        },
    )

    response = await generate_answer(question, chunks, licitacion_id, title, history=history)

    if page_counts:
        response.citations = validate_citations(response.citations, page_counts)

    latency_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "RAG query completed",
        extra={
            "query_id": query_id,
            "latency_ms": latency_ms,
            "model": LLM_MODEL,
            "citations_count": len(response.citations),
        },
    )

    return response

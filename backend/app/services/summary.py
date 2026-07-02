import json

from app.core.logging import get_logger
from app.models.schemas import SummaryResponse
from app.prompts.summary import SUMMARY_SYSTEM_PROMPT
from app.services.embeddings import get_openai_client
from app.services.query import hybrid_search

logger = get_logger(__name__)

LLM_MODEL = "resumidor_pliego-4o"
LLM_TEMPERATURE = 0.2

_SUMMARY_QUERIES = [
    "objeto del contrato descripción servicios presupuesto base licitación",
    "solvencia técnica económica requisitos acreditación medios",
    "criterios adjudicación baremo puntuación plazos fechas calendario",
]


async def generate_summary(licitacion_id: str, user_id: str, title: str) -> SummaryResponse:
    """
    Searches across all documents of the licitacion, then calls the LLM
    to produce a structured summary.
    """
    seen: set[str] = set()
    chunks: list[dict] = []
    for q in _SUMMARY_QUERIES:
        for chunk in await hybrid_search(q, licitacion_id, user_id, top_k=5):
            cid = chunk.get("chunk_id") or chunk.get("text", "")[:40]
            if cid not in seen:
                seen.add(cid)
                chunks.append(chunk)

    if not chunks:
        logger.warning(f"No chunks found for summary of licitacion {licitacion_id}.")
        return SummaryResponse(
            licitacion_id=licitacion_id,
            objeto="No se encontró información en los documentos de la licitación.",
            resumen="No se encontró información suficiente para generar el resumen.",
        )

    context = "\n\n".join(
        f"[{c.get('document_type', '')} p. {c.get('page_number', '?')}] {c['text']}"
        for c in chunks
    )

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI not configured — summary unavailable.")
        return SummaryResponse(
            licitacion_id=licitacion_id,
            objeto="Servicio de IA no disponible.",
            resumen="El servicio de generación de resúmenes no está disponible en este momento.",
        )

    try:
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": f"Licitación: '{title}'\n\nFragmentos:\n\n{context}"},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"LLM returned invalid JSON for summary of licitacion {licitacion_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Error generating summary for licitacion {licitacion_id}: {e}")
        raise

    return SummaryResponse(licitacion_id=licitacion_id, **data)

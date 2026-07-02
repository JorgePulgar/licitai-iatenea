"""
Eval del RAG tras el chunking por secciones + expansión por vecinos (paso 8).

Dos partes:
  A. Sanidad del índice (sin coste LLM): por licitación, cuántos chunks tienen
     `seq` y `section_heading` poblados → confirma que el reindex hizo efecto.
  B. Batería de preguntas (coste LLM + Search): ejecuta el pipeline real
     `query_licitacion` con un set fijo de preguntas extractivas universales de
     pliego y comprueba, por respuesta: si se respondió, nº de citas y que las
     páginas citadas existan en el documento (≤ page_count).

NO es un before/after: el reindex ya sobreescribió el índice antiguo. Mide el
estado POSTERIOR (validez de citas + cobertura de campos), no la mejora relativa.
La verificación semántica "la página citada contiene de verdad la afirmación"
requiere ojo humano — esto solo valida la trazabilidad de la cita.

Run from backend/ directory:
    python scripts/eval_rag.py                 # todas las licitaciones indexadas
    python scripts/eval_rag.py <licitacion_id> # solo esa
"""

import sys
import os
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import selectinload

from app.db.database import SessionLocal
from app.models.domain import Licitacion
from app.services.indexing import get_search_client
from app.services.query import query_licitacion, _NO_INFO_ANSWER

# Preguntas extractivas universales de pliego (no dependen del contenido concreto).
QUESTIONS = [
    "¿Cuál es el objeto del contrato?",
    "¿Cuál es el presupuesto base de licitación?",
    "¿Cuál es el plazo de ejecución del contrato?",
    "¿Qué requisitos de solvencia técnica se exigen?",
    "¿Cuáles son los criterios de adjudicación?",
    "¿Cuál es el plazo de presentación de ofertas?",
]


def _index_sanity(licitacion) -> None:
    """Parte A: % de chunks con seq / section_heading para los pliegos de la licitación."""
    client = get_search_client()
    if not client:
        print("  [índice] AI Search no configurado — se omite la sanidad del índice.")
        return

    pliego_ids = {p.id for p in licitacion.documents}
    lid = licitacion.id.lower()
    results = client.search(
        search_text="*",
        filter=f"licitacion_id eq '{lid}'",
        select=["pliego_id", "seq", "section_heading"],
        top=1000,
    )
    total = 0
    with_seq = 0
    with_heading = 0
    seen_pliegos = set()
    for r in results:
        total += 1
        seen_pliegos.add(r.get("pliego_id"))
        if r.get("seq") is not None:
            with_seq += 1
        if (r.get("section_heading") or "").strip():
            with_heading += 1

    if total == 0:
        print("  [índice] 0 chunks en el índice — ¿pliego sin indexar?")
        return
    pct_seq = 100 * with_seq / total
    pct_head = 100 * with_heading / total
    print(f"  [índice] {total} chunks | seq poblado: {pct_seq:.0f}% | "
          f"section_heading: {pct_head:.0f}% | pliegos: {len(seen_pliegos)}/{len(pliego_ids)}")
    if pct_seq < 100:
        print(f"  [índice] ⚠ {total - with_seq} chunks SIN seq (heredados, sin expansión por vecinos)")


async def _qa_battery(licitacion) -> tuple[int, int, int]:
    """Parte B: ejecuta las preguntas y devuelve (respondidas, con_citas, citas_invalidas)."""
    page_counts = {p.id: p.page_count for p in licitacion.documents if p.page_count is not None}
    answered = 0
    with_citations = 0
    invalid_citations = 0

    for q in QUESTIONS:
        resp = await query_licitacion(
            question=q,
            licitacion_id=licitacion.id,
            user_id=licitacion.user_id,
            title=licitacion.title,
            page_counts=page_counts,
        )
        is_answered = resp.answer.strip() != _NO_INFO_ANSWER.strip() and bool(resp.answer.strip())
        cited_pages = [c.page_number for c in resp.citations if c.page_number is not None]
        # Validez: la página citada debe existir en su pliego (≤ page_count).
        bad = [
            c.page_number for c in resp.citations
            if c.page_number is not None
            and page_counts.get(c.pliego_id) is not None
            and c.page_number > page_counts[c.pliego_id]
        ]
        answered += int(is_answered)
        with_citations += int(bool(resp.citations))
        invalid_citations += len(bad)

        status = "✓" if is_answered else "–"
        cite_str = f"{len(resp.citations)} citas (p. {sorted(set(cited_pages))})" if resp.citations else "sin citas"
        flag = f"  ⚠ {len(bad)} citas fuera de rango" if bad else ""
        print(f"    {status} {q[:48]:50} → {cite_str}{flag}")

    return answered, with_citations, invalid_citations


async def evaluate(licitacion_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        query = (
            db.query(Licitacion)
            .options(selectinload(Licitacion.documents))
            .filter(Licitacion.status.in_(("indexed", "partial_error")))
        )
        if licitacion_id:
            query = query.filter(Licitacion.id == licitacion_id)
        licitaciones = query.all()

        if not licitaciones:
            print("No hay licitaciones indexadas que evaluar.")
            return

        print(f"Evaluando {len(licitaciones)} licitación(es), {len(QUESTIONS)} preguntas cada una.\n")
        tot_q = tot_answered = tot_cited = tot_invalid = 0

        for lic in licitaciones:
            print(f"● {lic.title or lic.id}  ({lic.id})")
            _index_sanity(lic)
            answered, cited, invalid = await _qa_battery(lic)
            n = len(QUESTIONS)
            print(f"  → respondidas {answered}/{n} | con citas {cited}/{n} | citas inválidas {invalid}\n")
            tot_q += n
            tot_answered += answered
            tot_cited += cited
            tot_invalid += invalid

        print("─" * 60)
        print(f"TOTAL: respondidas {tot_answered}/{tot_q} | con citas {tot_cited}/{tot_q} | "
              f"citas inválidas {tot_invalid}")
        if tot_invalid == 0:
            print("Sin citas fuera de rango (trazabilidad de página OK).")
        else:
            print(f"⚠ {tot_invalid} citas apuntan a páginas inexistentes — revisar mapa de páginas.")
    finally:
        db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(evaluate(target))

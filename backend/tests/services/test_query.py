import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.query import _select_cited_chunks, _expand_neighbors, generate_answer


def _chunk(pliego_id, doc_type, page, text="x", score=1.0):
    return {
        "chunk_id": f"{pliego_id}-{page}",
        "pliego_id": pliego_id,
        "document_type": doc_type,
        "page_number": page,
        "text": text,
        "score": score,
    }


def test_keeps_only_cited_pages():
    chunks = [
        _chunk("p1", "pcap", 5),
        _chunk("p1", "pcap", 8),
        _chunk("p1", "pcap", 12),
    ]
    answer = "El plazo es de 30 días [pcap p. 5] y el presupuesto X [pcap p. 12]."
    result = _select_cited_chunks(answer, chunks)
    pages = sorted(c["page_number"] for c in result)
    assert pages == [5, 12]


def test_no_markers_returns_empty():
    chunks = [_chunk("p1", "pcap", 5), _chunk("p1", "pcap", 8)]
    answer = "Respuesta sin ninguna cita inline."
    assert _select_cited_chunks(answer, chunks) == []


def test_dedups_same_page_keeps_highest_score():
    chunks = [
        _chunk("p1", "pcap", 5, text="low", score=0.2),
        _chunk("p1", "pcap", 5, text="high", score=0.9),
    ]
    answer = "Dato [pcap p. 5]."
    result = _select_cited_chunks(answer, chunks)
    assert len(result) == 1
    assert result[0]["text"] == "high"


def test_doc_type_disambiguates_same_page():
    chunks = [
        _chunk("p1", "pcap", 3, text="pcap-page-3"),
        _chunk("p2", "ppt", 3, text="ppt-page-3"),
    ]
    answer = "Requisito técnico [ppt p. 3]."
    result = _select_cited_chunks(answer, chunks)
    assert len(result) == 1
    assert result[0]["text"] == "ppt-page-3"


def test_bare_marker_matches_any_doc_type_on_page():
    chunks = [
        _chunk("p1", "pcap", 3, text="pcap-page-3"),
        _chunk("p2", "ppt", 3, text="ppt-page-3"),
        _chunk("p1", "pcap", 9, text="page-9"),
    ]
    answer = "Afirmación [p. 3]."
    result = _select_cited_chunks(answer, chunks)
    pages = sorted(c["page_number"] for c in result)
    assert pages == [3, 3]  # both docs' page 3, not page 9


def test_cited_page_with_no_retrieved_chunk_is_dropped():
    chunks = [_chunk("p1", "pcap", 5)]
    answer = "Cita inventada [pcap p. 99]."
    assert _select_cited_chunks(answer, chunks) == []


# ── Neighbor expansion ─────────────────────────────────────────────────────────

def _hit(pliego_id, seq, page, chunk_id=None, score=1.0):
    return {
        "chunk_id": chunk_id or f"{pliego_id}-{seq}",
        "pliego_id": pliego_id,
        "licitacion_id": "lic-1",
        "document_type": "pcap",
        "filename": "doc.pdf",
        "text": f"t{seq}",
        "section_heading": "Sección",
        "page_number": page,
        "seq": seq,
        "score": score,
    }


def test_expand_neighbors_fetches_seq_neighbors_and_isolates():
    hit = _hit("p1", 5, 5)
    neighbors = [_hit("p1", 4, 4), _hit("p1", 6, 6)]
    mock_client = MagicMock()
    mock_client.search.return_value = neighbors

    with patch("app.services.query._get_search_client", return_value=mock_client):
        out = asyncio.run(_expand_neighbors([hit], "lic-1", "user-1"))

    assert sorted(c["seq"] for c in out) == [4, 5, 6]
    # Aislamiento: el filtro acota a la licitación y al usuario.
    flt = mock_client.search.call_args.kwargs["filter"]
    assert "licitacion_id eq 'lic-1'" in flt
    assert "user_id eq 'user-1'" in flt
    assert "seq eq 4" in flt and "seq eq 6" in flt
    # Los vecinos entran como contexto, sin puntuación (no compiten en el ranking).
    assert all(c["score"] == 0.0 for c in out if c["seq"] in (4, 6))


def test_expand_neighbors_dedups_already_retrieved():
    hits = [_hit("p1", 5, 5), _hit("p1", 6, 6)]
    # search devuelve 4, 7 y un duplicado de 6 (ya presente) → el dup se descarta.
    mock_client = MagicMock()
    mock_client.search.return_value = [_hit("p1", 4, 4), _hit("p1", 7, 7), _hit("p1", 6, 6)]

    with patch("app.services.query._get_search_client", return_value=mock_client):
        out = asyncio.run(_expand_neighbors(hits, "lic-1", "user-1"))

    assert sorted(c["seq"] for c in out) == [4, 5, 6, 7]
    assert len(out) == 4


def test_expand_neighbors_skips_chunks_without_seq():
    hits = [{"chunk_id": "c1", "pliego_id": "p1", "seq": None, "page_number": 3, "score": 1.0}]
    mock_client = MagicMock()

    with patch("app.services.query._get_search_client", return_value=mock_client):
        out = asyncio.run(_expand_neighbors(hits, "lic-1", "user-1"))

    assert out == hits
    mock_client.search.assert_not_called()


def test_expand_neighbors_returns_reading_order():
    hits = [_hit("p1", 6, 6), _hit("p1", 4, 4)]
    mock_client = MagicMock()
    mock_client.search.return_value = [_hit("p1", 5, 5)]

    with patch("app.services.query._get_search_client", return_value=mock_client):
        out = asyncio.run(_expand_neighbors(hits, "lic-1", "user-1"))

    assert [c["seq"] for c in out] == [4, 5, 6]


def _fake_llm(answer_text):
    """Cliente OpenAI falso que captura los mensajes y devuelve ``answer_text``."""
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer_text))])
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def test_generate_answer_threads_history_into_llm_messages():
    """Los turnos previos se reinyectan como user/assistant antes de la pregunta actual."""
    fake = _fake_llm("La duración es de 12 meses [pcap p. 5].")
    history = [("¿Cuál es el objeto?", "El objeto es el suministro X [pcap p. 1].")]

    with patch("app.services.query.get_openai_client", return_value=fake):
        asyncio.run(
            generate_answer(
                "¿Y la duración?",
                [_chunk("p1", "pcap", 5)],
                "lic-1",
                "Test",
                history=history,
            )
        )

    messages = fake.chat.completions.create.call_args.kwargs["messages"]
    roles = [m["role"] for m in messages]
    # system → turno previo (user+assistant) → pregunta actual (user).
    assert roles == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "¿Cuál es el objeto?"
    assert messages[2]["content"] == "El objeto es el suministro X [pcap p. 1]."
    assert "¿Y la duración?" in messages[3]["content"]


def test_generate_answer_without_history_is_stateless():
    """Sin historial, solo system + pregunta actual (no se inyectan turnos extra)."""
    fake = _fake_llm("Respuesta [pcap p. 2].")
    with patch("app.services.query.get_openai_client", return_value=fake):
        asyncio.run(generate_answer("Pregunta", [_chunk("p1", "pcap", 2)], "lic-1", "Test"))

    roles = [m["role"] for m in fake.chat.completions.create.call_args.kwargs["messages"]]
    assert roles == ["system", "user"]

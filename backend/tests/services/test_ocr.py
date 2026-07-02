import pytest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.ocr import (
    process_pliego,
    chunk_text,
    build_section_chunks,
    is_likely_scanned,
    check_analyze_confidence,
)

def test_is_likely_scanned_detects_scanned():
    # Simular un PDF que no devuelve texto
    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "   " # Casi nada de texto
    mock_reader.pages = [mock_page]
    
    with patch("app.services.ocr.PdfReader", return_value=mock_reader):
        assert is_likely_scanned(b"fake-bytes") is True

def test_is_likely_scanned_detects_native():
    # Simular un PDF con mucho texto
    mock_reader = MagicMock()
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Este es un documento con bastante texto nativo." * 10
    mock_reader.pages = [mock_page]
    
    with patch("app.services.ocr.PdfReader", return_value=mock_reader):
        assert is_likely_scanned(b"fake-bytes") is False

def test_check_analyze_confidence_warning(caplog):
    # Simular resultado con baja confianza
    result = MagicMock()
    page = MagicMock()
    page.words = [MagicMock(confidence=0.5), MagicMock(confidence=0.6)]
    result.pages = [page]
    
    with caplog.at_level("WARNING"):
        check_analyze_confidence(result, "pliego-test")
        assert "Low OCR quality" in caplog.text


# chunk_text gained document-context args in the S2 multi-doc refactor.
_CHUNK_CTX = dict(
    pliego_id="pliego-id",
    licitacion_id="lic-id",
    user_id="user-id",
    document_type="pcap",
    filename="doc.pdf",
)


def test_chunk_text_short_paragraph():
    text = "Este es un párrafo corto."
    chunks = chunk_text(text, 1, **_CHUNK_CTX)
    assert len(chunks) == 1
    assert chunks[0].content == text

def test_chunk_text_long_paragraph_coherence():
    text = ("Esta es una frase larga que se repite. " * 30)
    chunks = chunk_text(text, 1, **_CHUNK_CTX, chunk_size=400)
    assert len(chunks) > 1
    assert chunks[0].content.endswith(".")

# ── Section-aware chunking ────────────────────────────────────────────────────

_SEC_CTX = dict(
    pliego_id="pliego-id",
    licitacion_id="lic-id",
    user_id="user-id",
    document_type="pcap",
    filename="doc.pdf",
)


def _para(content, role=None, page=1, offset=0):
    return NS(
        content=content,
        role=role,
        bounding_regions=[NS(page_number=page)],
        spans=[NS(offset=offset, length=len(content))],
    )


def _table(rows, page=1, offset=0, length=100):
    cells = [
        NS(content=val, row_index=r, column_index=c)
        for r, row in enumerate(rows)
        for c, val in enumerate(row)
    ]
    return NS(cells=cells, bounding_regions=[NS(page_number=page)], spans=[NS(offset=offset, length=length)])


def _result(paragraphs=None, tables=None):
    return NS(paragraphs=paragraphs or [], tables=tables or [])


def test_section_chunks_group_by_heading():
    result = _result(paragraphs=[
        _para("Cláusula 1 — Objeto", role="sectionHeading", page=1, offset=0),
        _para("El objeto del contrato es el suministro X.", page=1, offset=20),
        _para("Cláusula 2 — Plazo", role="sectionHeading", page=2, offset=70),
        _para("El plazo de ejecución es de 12 meses.", page=2, offset=90),
    ])
    chunks = build_section_chunks(result, **_SEC_CTX)
    assert len(chunks) == 2
    assert chunks[0].section_heading == "Cláusula 1 — Objeto"
    assert chunks[0].content.startswith("Cláusula 1 — Objeto")
    assert "objeto del contrato" in chunks[0].content
    assert chunks[0].page_number == 1
    assert chunks[1].section_heading == "Cláusula 2 — Plazo"
    assert chunks[1].page_number == 2


def test_section_chunks_split_large_section_keeps_heading():
    big = "Frase de relleno número uno con suficiente longitud. " * 40  # > 800*1.2
    result = _result(paragraphs=[
        _para("Sección Grande", role="sectionHeading", page=3, offset=0),
        _para(big, page=3, offset=20),
    ])
    chunks = build_section_chunks(result, **_SEC_CTX)
    assert len(chunks) > 1
    for c in chunks:
        assert c.section_heading == "Sección Grande"
        assert c.content.startswith("Sección Grande")
        assert c.page_number == 3


def test_section_chunks_none_without_headings():
    result = _result(paragraphs=[
        _para("Solo texto sin encabezados.", role=None, page=1, offset=0),
        _para("Más texto plano sin secciones.", role=None, page=1, offset=40),
    ])
    assert build_section_chunks(result, **_SEC_CTX) is None


def test_section_chunk_page_is_first_char_page():
    result = _result(paragraphs=[
        _para("Encabezado", role="sectionHeading", page=5, offset=0),
        _para("Texto inicial en página cinco.", page=5, offset=20),
        _para("Continuación en página seis.", page=6, offset=60),
    ])
    chunks = build_section_chunks(result, **_SEC_CTX)
    # Cabe en un solo chunk → la cita apunta a la primera página de la sección.
    assert chunks[0].page_number == 5


def test_section_chunks_render_table_and_dedup_cell_paragraph():
    tbl = _table([["Importe", "Plazo"], ["1000", "30 días"]], page=2, offset=100, length=100)
    result = _result(
        paragraphs=[
            _para("Sección Tablas", role="sectionHeading", page=2, offset=0),
            _para("Texto introductorio.", page=2, offset=20),
            _para("Importe", page=2, offset=120),  # celda duplicada dentro del span de la tabla
        ],
        tables=[tbl],
    )
    chunks = build_section_chunks(result, **_SEC_CTX)
    joined = " ".join(c.content for c in chunks)
    assert "Importe | Plazo" in joined  # tabla renderizada fila a fila
    # El párrafo duplicado (offset 120, dentro de 100..200) no añade un fragmento suelto.
    assert joined.count("Importe") == 1


@patch("app.services.ocr.extract_title_llm", new_callable=AsyncMock, return_value=None)
@patch("app.services.ocr.validate_pdf_bytes")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr._call_document_intelligence")
@patch("app.services.ocr.settings")
@pytest.mark.asyncio
async def test_process_pliego_assigns_seq_and_sections(mock_settings, mock_di_call, mock_download, mock_validate, mock_title_llm):
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "http://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "key"
    mock_download.return_value = b"fake"
    mock_validate.return_value = None

    result = _result(paragraphs=[
        _para("Cláusula 1 — Objeto", role="sectionHeading", page=1, offset=0),
        _para("El objeto del contrato es el suministro X.", page=1, offset=20),
        _para("Cláusula 2 — Plazo", role="sectionHeading", page=2, offset=70),
        _para("El plazo de ejecución es de 12 meses.", page=2, offset=90),
    ])
    result.pages = [NS(words=None), NS(words=None)]
    mock_di_call.return_value = result

    with patch("app.services.ocr.is_likely_scanned", return_value=False):
        chunks, _quality, page_count, _title = await process_pliego(
            blob_url="url",
            pliego_id="id",
            licitacion_id="lic-id",
            user_id="user-id",
            document_type="pcap",
            filename="doc.pdf",
        )

    assert page_count == 2
    assert [c.seq for c in chunks] == list(range(len(chunks)))
    assert all(c.section_heading for c in chunks)


@patch("app.services.ocr.extract_title_llm", new_callable=AsyncMock, return_value=None)
@patch("app.services.ocr.validate_pdf_bytes")
@patch("app.services.ocr.download_pliego_bytes")
@patch("app.services.ocr._call_document_intelligence")
@patch("app.services.ocr.settings")
@pytest.mark.asyncio
async def test_process_pliego_scanned_flow(mock_settings, mock_di_call, mock_download, mock_validate, mock_title_llm):
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT = "http://mock"
    mock_settings.AZURE_DOCUMENT_INTELLIGENCE_KEY = "key"
    mock_download.return_value = b"fake"
    mock_validate.return_value = None

    # Mock is_likely_scanned para que devuelva True
    with patch("app.services.ocr.is_likely_scanned", return_value=True):
        region = MagicMock(page_number=1, polygon=[0, 0, 1, 0, 1, 1, 0, 1])
        para = MagicMock(content="Texto", bounding_regions=[region])
        mock_result = MagicMock(paragraphs=[para], pages=[MagicMock()])
        mock_di_call.return_value = mock_result

        chunks, quality_score, page_count, doc_title = await process_pliego(
            blob_url="url",
            pliego_id="id",
            licitacion_id="lic-id",
            user_id="user-id",
            document_type="pcap",
            filename="doc.pdf",
        )
        assert len(chunks) == 1
        assert page_count == 1

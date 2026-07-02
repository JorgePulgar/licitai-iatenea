import io
import uuid
import re
from typing import List
from pypdf import PdfReader
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

from app.core.config import settings
from app.core.logging import get_logger
from app.models.schemas import Chunk
from app.services.ingestion import download_pliego_bytes, validate_pdf_bytes

logger = get_logger(__name__)

SCAN_THRESHOLD_CHARS = 100
CONFIDENCE_THRESHOLD = 0.8
DI_MAX_RETRIES = 3
TITLE_LLM_MODEL = "extraccion_datos_4o"  # Azure OpenAI deployment para el fallback de título


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(DI_MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _call_document_intelligence(client: DocumentIntelligenceClient, pdf_bytes: bytes) -> AnalyzeResult:
    """Calls Azure Document Intelligence with exponential backoff + jitter on transient errors."""
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=io.BytesIO(pdf_bytes),
        content_type="application/pdf",
    )
    return poller.result()


def is_likely_scanned(pdf_bytes: bytes) -> bool:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        total_text = ""
        for i in range(min(len(reader.pages), 3)):
            text = reader.pages[i].extract_text() or ""
            total_text += text
        return len(total_text.strip()) < SCAN_THRESHOLD_CHARS
    except Exception:
        return True


def check_analyze_confidence(result: AnalyzeResult, pliego_id: str) -> float | None:
    """Returns avg word confidence across all pages, or None if no confidence data available.

    Threshold 0.8 chosen empirically: below this value scanned PDFs produce
    unreliable text that meaningfully degrades RAG answer quality.
    """
    confidences = []
    if not result.pages:
        return None

    for page in result.pages:
        if page.words:
            confidences.extend([w.confidence for w in page.words if w.confidence is not None])

    if not confidences:
        return None

    avg_conf = sum(confidences) / len(confidences)
    if avg_conf < CONFIDENCE_THRESHOLD:
        logger.warning(
            f"Low OCR quality for pliego {pliego_id}. Avg confidence: {avg_conf:.2f}."
        )
    else:
        logger.info(f"OCR quality for pliego {pliego_id}: {avg_conf:.2f}")
    return avg_conf


def extract_doc_title(result: AnalyzeResult) -> str | None:
    """Best-effort document title from page 1.

    Azure DI prebuilt-layout etiqueta cada párrafo con un `role`. El título de
    portada del pliego suele venir como role="title"; si no, el primer
    "sectionHeading" de la página 1 es una buena aproximación. Devuelve None si
    no hay candidato (la UI cae al filename). Trunca a 512 (límite de columna).
    """
    if not result.paragraphs:
        return None

    def on_page_1(paragraph) -> bool:
        return bool(paragraph.bounding_regions) and paragraph.bounding_regions[0].page_number == 1

    for role in ("title", "sectionHeading"):
        for paragraph in result.paragraphs:
            if getattr(paragraph, "role", None) == role and on_page_1(paragraph) and paragraph.content.strip():
                return paragraph.content.strip()[:512]
    return None


def _page1_text(result: AnalyzeResult) -> str:
    """Concatenates page-1 paragraph contents — input for the LLM title fallback."""
    if not result.paragraphs:
        return ""
    parts = [
        p.content.strip()
        for p in result.paragraphs
        if p.bounding_regions
        and p.bounding_regions[0].page_number == 1
        and p.content.strip()
    ]
    return "\n".join(parts)


async def extract_title_llm(page1_text: str) -> str | None:
    """LLM fallback for the document title when DI role tagging misses it.

    Las portadas con el título partido en muchas líneas no reciben role="title"
    de Azure DI; aquí pasamos el texto de la página 1 a gpt-4o-mini (T=0,
    extractivo) para reconstruirlo. Devuelve None si no hay título o el LLM no
    está disponible — nunca inventa (ver prompt y CLAUDE.md §8).
    """
    page1_text = page1_text.strip()
    if not page1_text:
        return None

    from app.prompts.title import TITLE_EXTRACTION_PROMPT
    from app.services.embeddings import get_openai_client

    client = get_openai_client()
    if not client:
        logger.warning("Azure OpenAI no disponible — sin fallback LLM para el título.")
        return None

    try:
        response = await client.chat.completions.create(
            model=TITLE_LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": TITLE_EXTRACTION_PROMPT},
                {"role": "user", "content": page1_text[:4000]},
            ],
        )
        title = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error(f"LLM title extraction failed: {e}")
        return None

    return title[:512] or None


async def extract_doc_title_from_blob(blob_url: str) -> str | None:
    """Re-OCRs a stored PDF only to extract its page-1 title (backfill helper).

    Prueba primero el role tagging de Azure DI; si falla, cae al LLM sobre el
    texto de la página 1. No toca chunks, embeddings ni índice. Devuelve None si
    Azure DI no está configurado o no hay título.
    """
    if not (settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and settings.AZURE_DOCUMENT_INTELLIGENCE_KEY):
        return None

    pdf_bytes = download_pliego_bytes(blob_url)
    client = DocumentIntelligenceClient(
        endpoint=settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY),
    )
    result = _call_document_intelligence(client, pdf_bytes)
    return extract_doc_title(result) or await extract_title_llm(_page1_text(result))


CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
# Margen sobre chunk_size: si el texto cabe en chunk_size*tolerance no se parte, y al
# buscar el corte por frase se admite rebasar el tamaño objetivo hasta este factor antes
# que cortar a mitad de frase.
CHUNK_TOLERANCE = 1.2
HEADING_ROLES = {"title", "sectionHeading"}


def _split_text_spans(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> List[tuple[int, int]]:
    """Parte `text` en spans (start, end) respetando límites de frase.

    Splitter puro y reutilizable: `chunk_text` (fallback por página/párrafo) y el
    chunking por secciones lo comparten para que el punto de corte sea idéntico
    (frase > espacio > duro). Devuelve offsets sobre `text` sin recortar espacios;
    quien construye el Chunk hace el `.strip()`.
    """
    n = len(text)
    if n == 0:
        return []
    if n <= chunk_size * CHUNK_TOLERANCE:
        return [(0, n)]

    spans: List[tuple[int, int]] = []
    start = 0
    while start < n:
        end = start + chunk_size

        if end < n:
            search_start = max(start, end - 200)
            last_sentence_end = -1

            matches = list(re.finditer(r'[.!?](\s+|$)', text[search_start:end + 50]))
            if matches:
                valid_matches = [
                    m for m in matches
                    if (search_start + m.end()) <= chunk_size * CHUNK_TOLERANCE + start
                ]
                if valid_matches:
                    last_sentence_end = search_start + valid_matches[-1].end()

            if last_sentence_end != -1:
                end = last_sentence_end
            else:
                last_space = text.rfind(" ", start, end)
                if last_space != -1 and last_space > start:
                    end = last_space

        spans.append((start, min(end, n)))

        start = end - overlap

        if end >= n:
            break

    return spans


def chunk_text(
    text: str,
    page_number: int,
    pliego_id: str,
    licitacion_id: str,
    user_id: str,
    document_type: str,
    filename: str,
    bounding_box: List[float] | None = None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[Chunk]:
    text = text.strip()
    if not text:
        return []

    chunks = []
    for start, end in _split_text_spans(text, chunk_size, overlap):
        chunk_content = text[start:end].strip()
        if chunk_content:
            chunks.append(Chunk(
                chunk_id=str(uuid.uuid4()),
                pliego_id=pliego_id,
                licitacion_id=licitacion_id,
                user_id=user_id,
                document_type=document_type,
                filename=filename,
                content=chunk_content,
                page_number=page_number,
                bounding_box=bounding_box,
            ))
    return chunks


def _render_table(table) -> str:
    """Aplana una tabla de Azure DI a texto fila a fila (celdas separadas por ' | ').

    El chunker es textual; convertir la tabla a líneas preserva la asociación
    fila/columna mucho mejor que volcar las celdas sueltas (comportamiento previo,
    que perdía la estructura de las páginas de criterios/presupuesto).
    """
    rows: dict[int, list[tuple[int, str]]] = {}
    for cell in (table.cells or []):
        if cell.content and cell.content.strip():
            rows.setdefault(cell.row_index, []).append((cell.column_index, cell.content.strip()))
    lines = []
    for r in sorted(rows):
        cells = [content for _, content in sorted(rows[r])]
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def _ordered_elements(result: AnalyzeResult) -> list[dict]:
    """Ordena párrafos y tablas en orden de lectura usando el offset de su span.

    Azure DI entrega `paragraphs` y `tables` por separado; el texto de las celdas
    suele duplicarse como párrafos. Ordenamos por offset y descartamos los párrafos
    cuyo span cae dentro de una tabla (dedup), evitando contar dos veces ese texto.
    Cada elemento lleva su página y si es un encabezado de sección (role tagging).
    """
    tables = result.tables or []
    table_ranges = [
        (t.spans[0].offset, t.spans[0].offset + t.spans[0].length)
        for t in tables if t.spans
    ]

    def inside_table(offset: int | None) -> bool:
        return offset is not None and any(s <= offset < e for s, e in table_ranges)

    elems: list[dict] = []
    for p in (result.paragraphs or []):
        text = p.content.strip() if p.content else ""
        if not text:
            continue
        offset = p.spans[0].offset if p.spans else None
        if inside_table(offset):
            continue  # ya lo capturará _render_table; no duplicar
        page = p.bounding_regions[0].page_number if p.bounding_regions else 1
        elems.append({
            "offset": offset,
            "text": text,
            "page": page,
            "heading": getattr(p, "role", None) in HEADING_ROLES,
        })

    for t in tables:
        text = _render_table(t)
        if not text:
            continue
        page = t.bounding_regions[0].page_number if t.bounding_regions else 1
        offset = t.spans[0].offset if t.spans else None
        elems.append({"offset": offset, "text": text, "page": page, "heading": False})

    # Los elementos sin offset (raro) van al final, sin romper el orden de los demás.
    elems.sort(key=lambda e: e["offset"] if e["offset"] is not None else 1 << 62)
    return elems


def _chunk_one_section(
    heading: str | None,
    items: list[tuple[str, int]],
    pliego_id: str,
    licitacion_id: str,
    user_id: str,
    document_type: str,
    filename: str,
) -> List[Chunk]:
    """Convierte una sección (encabezado + sus párrafos/tablas) en chunks.

    Une el cuerpo manteniendo un mapa carácter→página, parte con el splitter por
    frases y, en cada trozo, antepone el encabezado al contenido (pureza del
    embedding + contexto de cita) y le asigna la página del primer carácter real.
    """
    if not items:
        return []

    body_parts: list[str] = []
    page_per_char: list[int] = []
    for i, (text, page) in enumerate(items):
        if i > 0:
            body_parts.append("\n")
            page_per_char.append(page)
        body_parts.append(text)
        page_per_char.extend([page] * len(text))
    body = "".join(body_parts)

    chunks: List[Chunk] = []
    for start, end in _split_text_spans(body):
        piece = body[start:end].strip()
        if not piece:
            continue
        # Página del primer carácter no-espacio del trozo (la cita debe apuntar a
        # donde empieza el texto real, no a un salto de línea de separación).
        idx = start
        while idx < end and body[idx].isspace():
            idx += 1
        page = page_per_char[idx] if idx < len(page_per_char) else page_per_char[start]
        content = f"{heading}\n\n{piece}" if heading else piece
        chunks.append(Chunk(
            chunk_id=str(uuid.uuid4()),
            pliego_id=pliego_id,
            licitacion_id=licitacion_id,
            user_id=user_id,
            document_type=document_type,
            filename=filename,
            content=content,
            page_number=page,
            section_heading=heading,
        ))
    return chunks


def build_section_chunks(
    result: AnalyzeResult,
    pliego_id: str,
    licitacion_id: str,
    user_id: str,
    document_type: str,
    filename: str,
) -> List[Chunk] | None:
    """Chunking por secciones del documento (role="sectionHeading" de Azure DI).

    Agrupa los elementos en secciones, parte cada sección en chunks limpios y
    devuelve la lista en orden de lectura. Devuelve None si el documento no trae
    ningún encabezado de sección (PDF escaneado/plano) para que el llamador caiga
    al chunking por página heredado.
    """
    elems = _ordered_elements(result)
    if not elems or not any(e["heading"] for e in elems):
        return None

    chunks: List[Chunk] = []
    cur_heading: str | None = None
    cur_items: list[tuple[str, int]] = []

    def flush() -> None:
        chunks.extend(_chunk_one_section(
            cur_heading, cur_items,
            pliego_id, licitacion_id, user_id, document_type, filename,
        ))

    for e in elems:
        if e["heading"]:
            flush()
            cur_heading = e["text"]
            cur_items = []
        else:
            cur_items.append((e["text"], e["page"]))
    flush()

    return chunks


async def process_pliego(
    blob_url: str,
    pliego_id: str,
    licitacion_id: str,
    user_id: str,
    document_type: str,
    filename: str,
) -> tuple[List[Chunk], float | None, int | None, str | None]:
    """
    Downloads a PDF from storage, validates it, runs OCR (Azure DI or pypdf fallback),
    and returns (chunks, ocr_quality_score, page_count, doc_title). quality_score is None
    when Azure DI is not used (pypdf fallback has no per-word confidence data). page_count is
    the document's actual page count — used by citation validation (LIC-057) as the max valid
    page number. Never derive it from chunk page numbers: pages without extracted chunks
    (blank/image-only) would shrink it and wrongly filter legitimate citations. doc_title is
    the title extracted from page 1 (Azure DI only); None with the pypdf fallback.
    """
    try:
        pdf_bytes = download_pliego_bytes(blob_url)
    except Exception as e:
        logger.error(f"Error downloading pliego {pliego_id}: {e}")
        raise ValueError(f"Could not download document: {e}")

    validate_pdf_bytes(pdf_bytes, filename)

    scanned = is_likely_scanned(pdf_bytes)
    logger.info(
        f"Pliego {pliego_id} ({document_type}) detected as "
        f"{'scanned' if scanned else 'native'} PDF."
    )

    chunks: List[Chunk] = []
    quality_score: float | None = None
    page_count: int | None = None
    doc_title: str | None = None

    if settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and settings.AZURE_DOCUMENT_INTELLIGENCE_KEY:
        logger.info(f"Processing {pliego_id} with Azure Document Intelligence...")
        try:
            client = DocumentIntelligenceClient(
                endpoint=settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
                credential=AzureKeyCredential(settings.AZURE_DOCUMENT_INTELLIGENCE_KEY)
            )
            result: AnalyzeResult = _call_document_intelligence(client, pdf_bytes)

            quality_score = check_analyze_confidence(result, pliego_id)
            page_count = len(result.pages) if result.pages else None
            # Role tagging primero (rápido, sin coste LLM); si la portada no trae
            # role="title" (común en PCT), fallback al LLM sobre el texto de la página 1.
            doc_title = extract_doc_title(result) or await extract_title_llm(_page1_text(result))

            if result.paragraphs or result.tables:
                # Chunking por secciones (role="sectionHeading"): mantiene cada sección
                # semánticamente pura → embeddings más limpios y citas más completas.
                section_chunks = build_section_chunks(
                    result, pliego_id, licitacion_id, user_id, document_type, filename,
                )
                if section_chunks is not None:
                    chunks.extend(section_chunks)
                    logger.info(
                        f"Section-aware chunking for {pliego_id}: {len(section_chunks)} chunks."
                    )
                else:
                    # Sin encabezados de sección (PDF escaneado/plano): fallback al chunking
                    # por página heredado. Combina párrafos + celdas de tabla agrupados por
                    # página para no perder páginas con muchas tablas (criterios, presupuesto).
                    logger.info(
                        f"No section headings in {pliego_id}; using page-grouped chunking."
                    )
                    page_texts: dict[int, list[str]] = {}

                    for paragraph in (result.paragraphs or []):
                        page_num = (
                            paragraph.bounding_regions[0].page_number
                            if paragraph.bounding_regions
                            else 1
                        )
                        if paragraph.content.strip():
                            page_texts.setdefault(page_num, []).append(paragraph.content.strip())

                    for table in (result.tables or []):
                        for cell in (table.cells or []):
                            if cell.content and cell.content.strip():
                                page_num = (
                                    cell.bounding_regions[0].page_number
                                    if cell.bounding_regions
                                    else 1
                                )
                                page_texts.setdefault(page_num, []).append(cell.content.strip())

                    for page_num in sorted(page_texts):
                        page_text = "\n".join(page_texts[page_num])
                        page_chunks = chunk_text(
                            page_text, page_num,
                            pliego_id, licitacion_id, user_id, document_type, filename,
                        )
                        chunks.extend(page_chunks)
            else:
                logger.warning(f"No paragraphs or tables found in {pliego_id} with Azure DI.")

        except Exception as e:
            # exc_info=True → se registra como excepción en App Insights (LIC-101/103).
            logger.error(
                f"Azure Document Intelligence error for {pliego_id}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"OCR error: {e}")
    else:
        logger.warning(f"Azure DI not configured. Using pypdf fallback for {pliego_id}.")
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes))
            page_count = len(reader.pages)
            for i, page in enumerate(reader.pages):
                page_number = i + 1
                text = page.extract_text()
                if text:
                    paragraphs = [p for p in text.split("\n\n") if p.strip()]
                    for p in paragraphs:
                        paragraph_chunks = chunk_text(
                            p.strip(), page_number,
                            pliego_id, licitacion_id, user_id, document_type, filename,
                        )
                        chunks.extend(paragraph_chunks)
        except Exception as e:
            logger.error(f"pypdf fallback error for {pliego_id}: {e}")
            raise RuntimeError(f"Error processing PDF locally: {e}")

    # Ordinal de lectura global del pliego (todas las rutas: secciones, página, pypdf).
    # Es la clave de la expansión por vecinos en la búsqueda (recuperar seq±1).
    for i, c in enumerate(chunks):
        c.seq = i

    return chunks, quality_score, page_count, doc_title

"""Texto real por página de los PDF fixture — insumo del juez de fidelidad (S3).

S3 debe juzgar contra el texto REAL de la página citada, no contra los chunks
recuperados (checklist spec 5.3 §8). Como el pipeline no persiste texto por
página, se extrae en el momento con pypdf desde el PDF local.

Limitación conocida (deuda registrada): pypdf solo sirve para PDF nativos. Un
pliego escaneado devuelve texto vacío → el runner marca la cita como
``page_text_unavailable`` en lugar de emitir un veredicto falso.
"""

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader


class FixturePageTextProvider:
    """Resuelve (document_type, filename, page_number) → texto de página.

    ``documents`` mapea cada document_type del golden a su PDF local. La página
    es 1-indexada (convención de Document Intelligence y de las citas [p. N]).
    """

    def __init__(self, documents: dict[str, Path]):
        missing = [str(p) for p in documents.values() if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"PDF fixture no encontrado: {missing}")
        self._documents = documents

    def get(self, document_type: str, filename: str, page_number: int) -> str | None:
        """Texto de la página, o None si el documento/página no se resuelve o no tiene texto."""
        path = self._documents.get(document_type)
        if path is None:
            # Citas heredadas sin document_type: intenta casar por nombre de fichero.
            path = next(
                (p for p in self._documents.values() if p.name == filename), None
            )
        if path is None:
            return None
        text = _extract_page_text(path, page_number)
        return text if text and text.strip() else None


@lru_cache(maxsize=256)
def _extract_page_text(pdf_path: Path, page_number: int) -> str | None:
    reader = _get_reader(pdf_path)
    if page_number < 1 or page_number > len(reader.pages):
        return None
    return reader.pages[page_number - 1].extract_text() or None


@lru_cache(maxsize=8)
def _get_reader(pdf_path: Path) -> PdfReader:
    return PdfReader(str(pdf_path))

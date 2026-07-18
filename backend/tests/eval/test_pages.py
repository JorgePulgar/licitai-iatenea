"""Tests del proveedor de texto por página (insumo del juez S3) contra PDF fixture reales."""

from pathlib import Path

import pytest

from eval.pages import FixturePageTextProvider

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pliegos"
PCAP_PDF = FIXTURES_DIR / "PCA_Servicio mentorías en digitalización a empresas de turismo (PRTR).pdf"


@pytest.fixture
def provider():
    return FixturePageTextProvider({"pcap": PCAP_PDF})


class TestFixturePageTextProvider:
    def test_extracts_text_from_native_pdf(self, provider):
        text = provider.get("pcap", PCAP_PDF.name, 1)
        assert text is not None
        assert len(text.strip()) > 50

    def test_page_out_of_range_returns_none(self, provider):
        assert provider.get("pcap", PCAP_PDF.name, 9999) is None

    def test_page_zero_returns_none(self, provider):
        assert provider.get("pcap", PCAP_PDF.name, 0) is None

    def test_unknown_document_type_falls_back_to_filename(self, provider):
        # Cita heredada sin document_type: casa por nombre de fichero.
        text = provider.get("", PCAP_PDF.name, 1)
        assert text is not None

    def test_unknown_type_and_filename_returns_none(self, provider):
        assert provider.get("ppt", "otro.pdf", 1) is None

    def test_missing_pdf_raises_at_construction(self):
        with pytest.raises(FileNotFoundError):
            FixturePageTextProvider({"pcap": FIXTURES_DIR / "no-existe.pdf"})

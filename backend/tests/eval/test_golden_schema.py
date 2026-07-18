"""Validación del esquema golden y de los ficheros committeados (DM9)."""

from pathlib import Path

import pytest

from eval.schema import (
    GoldenDataset,
    GoldenValidationError,
    load_all_golden,
    load_golden,
)

GOLDEN_DIR = Path(__file__).resolve().parents[2] / "eval" / "golden"


def _base_data(**overrides):
    data = {
        "dataset_version": 1,
        "key": "test-pliego",
        "title": "Pliego de prueba",
        "status": "draft",
        "documents": [{"document_type": "pcap", "filename": "test.pdf"}],
        "qa": [{"id": "q01", "question": "¿Cuál es el objeto del contrato?"}],
        "unanswerable": [{"id": "u01", "question": "¿Exige ISO 27001?"}],
    }
    data.update(overrides)
    return data


class TestGoldenSchema:
    def test_valid_draft(self):
        ds = GoldenDataset.model_validate(_base_data())
        assert ds.key == "test-pliego"
        assert ds.status == "draft"

    def test_labeled_requires_min_counts(self):
        with pytest.raises(ValueError, match="labeled"):
            GoldenDataset.model_validate(_base_data(status="labeled"))

    def test_labeled_with_enough_items_passes(self):
        qa = [{"id": f"q{i:02d}", "question": f"Pregunta {i}"} for i in range(10)]
        una = [{"id": f"u{i:02d}", "question": f"Ausente {i}"} for i in range(3)]
        ds = GoldenDataset.model_validate(
            _base_data(status="labeled", qa=qa, unanswerable=una)
        )
        assert ds.status == "labeled"

    def test_duplicate_ids_across_sections_rejected(self):
        data = _base_data(
            qa=[{"id": "x01", "question": "A"}],
            unanswerable=[{"id": "x01", "question": "B"}],
        )
        with pytest.raises(ValueError, match="duplicados"):
            GoldenDataset.model_validate(data)

    def test_invalid_document_type_rejected(self):
        data = _base_data(documents=[{"document_type": "memoria", "filename": "x.pdf"}])
        with pytest.raises(ValueError, match="document_type"):
            GoldenDataset.model_validate(data)

    def test_duplicate_document_type_rejected(self):
        data = _base_data(
            documents=[
                {"document_type": "pcap", "filename": "a.pdf"},
                {"document_type": "pcap", "filename": "b.pdf"},
            ]
        )
        with pytest.raises(ValueError, match="duplicado"):
            GoldenDataset.model_validate(data)

    def test_invalid_status_rejected(self):
        with pytest.raises(ValueError, match="status"):
            GoldenDataset.model_validate(_base_data(status="final"))

    def test_pages_must_be_positive(self):
        data = _base_data(qa=[{"id": "q01", "question": "X", "expected_pages": [0]}])
        with pytest.raises(ValueError, match="expected_pages"):
            GoldenDataset.model_validate(data)


class TestGoldenLoading:
    def test_invalid_yaml_raises_with_filename(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("key: [unclosed", encoding="utf-8")
        with pytest.raises(GoldenValidationError, match="bad.yaml"):
            load_golden(bad)

    def test_non_mapping_yaml_rejected(self, tmp_path):
        bad = tmp_path / "list.yaml"
        bad.write_text("- item", encoding="utf-8")
        with pytest.raises(GoldenValidationError, match="mapping"):
            load_golden(bad)

    def test_duplicate_keys_across_files_rejected(self, tmp_path):
        import yaml

        for name in ("a.yaml", "b.yaml"):
            (tmp_path / name).write_text(
                yaml.safe_dump(_base_data()), encoding="utf-8", errors="strict"
            )
        with pytest.raises(GoldenValidationError, match="duplicadas"):
            load_all_golden(tmp_path)


class TestCommittedGoldenFiles:
    """Los ficheros golden del repo deben validar siempre (esqueletos incluidos)."""

    def test_all_committed_files_validate(self):
        datasets = load_all_golden(GOLDEN_DIR)
        assert len(datasets) >= 2
        keys = {d.key for d in datasets}
        assert {"mentorias-turismo", "obras-2026-00048"} <= keys

    def test_committed_documents_exist_in_fixtures(self):
        fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "pliegos"
        for ds in load_all_golden(GOLDEN_DIR):
            for doc in ds.documents:
                assert (fixtures / doc.filename).is_file(), (
                    f"{ds.key}: fixture no encontrado: {doc.filename}"
                )

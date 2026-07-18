"""Esquema y carga del golden dataset de evaluación (spec 5.3, subset DM9).

Un fichero golden por licitación fixture (`eval/golden/<key>.yaml`). El campo
``status`` distingue esqueletos en etiquetado (``draft``) de datasets listos
(``labeled``): los mínimos de tamaño (qa ≥ 10, unanswerable ≥ 3) solo se
exigen a los ``labeled``, y el runner rechaza ``draft`` salvo flag explícito.

Cualquier cambio de etiquetas ⇒ subir ``dataset_version`` ⇒ nuevo baseline.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

VALID_DOCUMENT_TYPES = {"pcap", "ppt", "anexo"}

LABELED_MIN_QA = 10
LABELED_MIN_UNANSWERABLE = 3


class GoldenValidationError(ValueError):
    """El fichero golden no cumple el esquema o sus invariantes."""


class GoldenDocument(BaseModel):
    document_type: str
    filename: str = Field(min_length=1)

    @field_validator("document_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in VALID_DOCUMENT_TYPES:
            raise ValueError(
                f"document_type '{v}' inválido; debe ser uno de {sorted(VALID_DOCUMENT_TYPES)}"
            )
        return v


class GoldenQA(BaseModel):
    """Pregunta respondible con el pliego. S3 juzga la fidelidad de la respuesta.

    ``expected_pages`` / ``expected_answer`` son opcionales en el subset DM9
    (alimentarán S1/S2 cuando lleguen; etiquetarlos ya evita releer el pliego).
    """

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_pages: list[int] | None = None
    expected_answer: str | None = None

    @field_validator("expected_pages")
    @classmethod
    def _positive_pages(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(p < 1 for p in v):
            raise ValueError("expected_pages debe contener números de página ≥ 1")
        return v


class GoldenUnanswerable(BaseModel):
    """Pregunta plausible cuya respuesta NO está en el pliego. S4 exige rechazo."""

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)


class GoldenDataset(BaseModel):
    dataset_version: int = Field(ge=1)
    key: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1)
    status: str = "draft"
    documents: list[GoldenDocument] = Field(min_length=1)
    qa: list[GoldenQA] = Field(default_factory=list)
    unanswerable: list[GoldenUnanswerable] = Field(default_factory=list)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in {"draft", "labeled"}:
            raise ValueError("status debe ser 'draft' o 'labeled'")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> "GoldenDataset":
        ids = [item.id for item in self.qa] + [item.id for item in self.unanswerable]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"ids duplicados en qa/unanswerable: {sorted(dupes)}")

        doc_types = [d.document_type for d in self.documents]
        dup_types = {t for t in doc_types if doc_types.count(t) > 1}
        if dup_types:
            raise ValueError(f"document_type duplicado en documents: {sorted(dup_types)}")

        if self.status == "labeled":
            if len(self.qa) < LABELED_MIN_QA:
                raise ValueError(
                    f"dataset 'labeled' requiere ≥ {LABELED_MIN_QA} preguntas qa "
                    f"(hay {len(self.qa)})"
                )
            if len(self.unanswerable) < LABELED_MIN_UNANSWERABLE:
                raise ValueError(
                    f"dataset 'labeled' requiere ≥ {LABELED_MIN_UNANSWERABLE} preguntas "
                    f"unanswerable (hay {len(self.unanswerable)})"
                )
        return self


def load_golden(path: Path) -> GoldenDataset:
    """Carga y valida un fichero golden. Lanza GoldenValidationError con contexto."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise GoldenValidationError(f"{path.name}: YAML inválido — {e}") from e
    if not isinstance(raw, dict):
        raise GoldenValidationError(f"{path.name}: el fichero debe ser un mapping YAML")
    try:
        return GoldenDataset.model_validate(raw)
    except ValueError as e:
        raise GoldenValidationError(f"{path.name}: {e}") from e


def load_all_golden(golden_dir: Path) -> list[GoldenDataset]:
    """Carga todos los `*.yaml` del directorio golden, ordenados por key."""
    datasets = [load_golden(p) for p in sorted(golden_dir.glob("*.yaml"))]
    keys = [d.key for d in datasets]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise GoldenValidationError(f"keys duplicadas entre ficheros golden: {sorted(dupes)}")
    return datasets

"""Lógica pura de las suites S3 (faithfulness) y S4 (refusal) — spec 5.3, subset DM9.

Sin dependencias de Azure: el pipeline RAG, el juez LLM y el texto de página
entran inyectados como callables. ``run.py`` cablea los reales; los tests
inyectan fakes y ejercitan métricas y gate offline.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from eval.judges.faithfulness import JudgeParseError
from eval.schema import GoldenDataset

# Umbrales DM9 (spec-demo-minimal §7.4 / spec 5.3 §5).
S3_FAITHFULNESS_FLOOR = 0.95
S4_FALSE_ANSWERS_MAX = 0

# Callable que ejecuta el pipeline RAG real: pregunta → QueryResponse (duck-typed:
# .answer, .citations[.page_number/.document_type/.filename], .tokens_*).
QueryFn = Callable[[str], Awaitable[Any]]
# Callable juez: (question, answer, document_type, page_number, page_text)
# → (verdict, rationale). Puede lanzar JudgeParseError.
JudgeFn = Callable[[str, str, str, int, str], Awaitable[tuple[str, str]]]


class PageTextFn(Protocol):
    def __call__(self, document_type: str, filename: str, page_number: int) -> str | None: ...


class DraftDatasetError(ValueError):
    """El dataset sigue en 'draft'; el runner exige 'labeled' salvo flag explícito."""


@dataclass
class CitationJudgement:
    document_type: str
    page_number: int
    verdict: str  # supported | not_supported | page_text_unavailable | judge_error
    rationale: str


@dataclass
class S3ItemResult:
    qa_id: str
    question: str
    answer: str
    answered: bool
    judgements: list[CitationJudgement] = field(default_factory=list)
    latency_ms: int = 0
    tokens_prompt: int | None = None
    tokens_completion: int | None = None


@dataclass
class S3Result:
    golden_key: str
    items: list[S3ItemResult]
    metrics: dict[str, Any]


@dataclass
class S4ItemResult:
    item_id: str
    question: str
    answer: str
    refused: bool
    latency_ms: int = 0


@dataclass
class S4Result:
    golden_key: str
    items: list[S4ItemResult]
    metrics: dict[str, Any]


@dataclass
class GateResult:
    passed: bool
    reasons: list[str]


def _check_runnable(golden: GoldenDataset, allow_draft: bool) -> None:
    if golden.status != "labeled" and not allow_draft:
        raise DraftDatasetError(
            f"golden '{golden.key}' está en status '{golden.status}'; "
            "etiqueta el dataset (status: labeled) o usa --allow-draft"
        )


async def run_s3(
    golden: GoldenDataset,
    query_fn: QueryFn,
    judge_fn: JudgeFn,
    page_text_fn: PageTextFn,
    no_info_answer: str,
    allow_draft: bool = False,
) -> S3Result:
    """S3 faithfulness: cada cita de cada respuesta, ¿la respalda su página real?"""
    _check_runnable(golden, allow_draft)
    items: list[S3ItemResult] = []

    for qa in golden.qa:
        t0 = time.monotonic()
        resp = await query_fn(qa.question)
        latency_ms = int((time.monotonic() - t0) * 1000)

        answer = (resp.answer or "").strip()
        answered = answer != no_info_answer.strip() and bool(answer)
        item = S3ItemResult(
            qa_id=qa.id,
            question=qa.question,
            answer=answer,
            answered=answered,
            latency_ms=latency_ms,
            tokens_prompt=getattr(resp, "tokens_prompt", None),
            tokens_completion=getattr(resp, "tokens_completion", None),
        )

        if answered:
            for cit in resp.citations:
                page = cit.page_number
                if page is None:
                    continue
                doc_type = cit.document_type or ""
                page_text = page_text_fn(doc_type, cit.filename or "", page)
                if page_text is None:
                    item.judgements.append(
                        CitationJudgement(doc_type, page, "page_text_unavailable",
                                          "sin texto de página (¿PDF escaneado o página fuera de rango?)")
                    )
                    continue
                try:
                    verdict, rationale = await judge_fn(
                        qa.question, answer, doc_type, page, page_text
                    )
                    item.judgements.append(CitationJudgement(doc_type, page, verdict, rationale))
                except JudgeParseError as e:
                    item.judgements.append(
                        CitationJudgement(doc_type, page, "judge_error", str(e))
                    )

        items.append(item)

    supported = sum(
        1 for it in items for j in it.judgements if j.verdict == "supported"
    )
    not_supported = sum(
        1 for it in items for j in it.judgements if j.verdict == "not_supported"
    )
    unavailable = sum(
        1 for it in items for j in it.judgements if j.verdict == "page_text_unavailable"
    )
    judge_errors = sum(
        1 for it in items for j in it.judgements if j.verdict == "judge_error"
    )
    judged = supported + not_supported
    metrics = {
        "questions": len(items),
        "answered": sum(1 for it in items if it.answered),
        "refused_answerable": sum(1 for it in items if not it.answered),
        "answered_without_citation": sum(
            1 for it in items if it.answered and not it.judgements
        ),
        "citations_judged": judged,
        "supported": supported,
        "not_supported": not_supported,
        "page_text_unavailable": unavailable,
        "judge_errors": judge_errors,
        "faithfulness": round(supported / judged, 4) if judged else None,
    }
    return S3Result(golden_key=golden.key, items=items, metrics=metrics)


async def run_s4(
    golden: GoldenDataset,
    query_fn: QueryFn,
    no_info_answer: str,
    allow_draft: bool = False,
) -> S4Result:
    """S4 refusal: las preguntas sin respuesta en el pliego deben devolver EXACTAMENTE
    la respuesta canónica de no-información. Igualdad estricta con la constante, no
    substring: una alucinación con tono de disculpa que la contenga debe contar como
    respuesta falsa (checklist spec 5.3 §8).
    """
    _check_runnable(golden, allow_draft)
    items: list[S4ItemResult] = []

    for u in golden.unanswerable:
        t0 = time.monotonic()
        resp = await query_fn(u.question)
        latency_ms = int((time.monotonic() - t0) * 1000)
        answer = (resp.answer or "").strip()
        refused = answer == no_info_answer.strip()
        items.append(
            S4ItemResult(
                item_id=u.id,
                question=u.question,
                answer=answer,
                refused=refused,
                latency_ms=latency_ms,
            )
        )

    false_answers = sum(1 for it in items if not it.refused)
    metrics = {
        "questions": len(items),
        "refused": sum(1 for it in items if it.refused),
        "false_answers": false_answers,
        "false_answer_rate": round(false_answers / len(items), 4) if items else None,
    }
    return S4Result(golden_key=golden.key, items=items, metrics=metrics)


def evaluate_gate(
    s3_results: list[S3Result], s4_results: list[S4Result]
) -> GateResult:
    """Gate DM9: faithfulness ≥ 0.95, respuestas falsas = 0, todo lo afirmado citado.

    La faithfulness gating es agregada sobre TODAS las citas juzgadas (no la media
    de medias: una licitación con 2 citas no pesa como una con 40).
    """
    reasons: list[str] = []

    supported = sum(r.metrics["supported"] for r in s3_results)
    judged = sum(r.metrics["citations_judged"] for r in s3_results)
    if judged == 0:
        reasons.append("S3: 0 citas juzgadas — no hay señal de faithfulness")
    else:
        faithfulness = supported / judged
        if faithfulness < S3_FAITHFULNESS_FLOOR:
            reasons.append(
                f"S3: faithfulness {faithfulness:.4f} < suelo {S3_FAITHFULNESS_FLOOR}"
            )

    uncited = sum(r.metrics["answered_without_citation"] for r in s3_results)
    if uncited > 0:
        reasons.append(
            f"S3: {uncited} respuesta(s) afirmativa(s) sin ninguna cita "
            "(viola 'sin cita, sin afirmación')"
        )

    false_answers = sum(r.metrics["false_answers"] for r in s4_results)
    if false_answers > S4_FALSE_ANSWERS_MAX:
        reasons.append(
            f"S4: {false_answers} respuesta(s) falsa(s) a preguntas sin respuesta "
            f"(máximo {S4_FALSE_ANSWERS_MAX})"
        )

    return GateResult(passed=not reasons, reasons=reasons)

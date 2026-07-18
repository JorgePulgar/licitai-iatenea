"""Tests offline de las suites S3/S4 y del gate DM9 — pipeline y juez inyectados como fakes."""

from types import SimpleNamespace

import pytest

from eval.judges.faithfulness import JudgeParseError
from eval.runner import (
    DraftDatasetError,
    S3Result,
    S4Result,
    evaluate_gate,
    run_s3,
    run_s4,
)
from eval.schema import GoldenDataset

NO_INFO = (
    "No he encontrado información sobre esto en el pliego. "
    "Prueba con otra formulación."
)


def _golden(qa=None, unanswerable=None, status="draft"):
    qa = qa if qa is not None else [
        {"id": f"q{i:02d}", "question": f"Pregunta {i}"} for i in range(10)
    ]
    unanswerable = unanswerable if unanswerable is not None else [
        {"id": f"u{i:02d}", "question": f"Ausente {i}"} for i in range(3)
    ]
    return GoldenDataset.model_validate({
        "dataset_version": 1,
        "key": "test-pliego",
        "title": "Pliego de prueba",
        "status": status,
        "documents": [{"document_type": "pcap", "filename": "test.pdf"}],
        "qa": qa,
        "unanswerable": unanswerable,
    })


def _citation(page, doc_type="pcap", filename="test.pdf"):
    return SimpleNamespace(page_number=page, document_type=doc_type, filename=filename)


def _response(answer, citations=(), tokens=(100, 50)):
    return SimpleNamespace(
        answer=answer,
        citations=list(citations),
        tokens_prompt=tokens[0],
        tokens_completion=tokens[1],
    )


async def _judge_always_supported(question, answer, doc_type, page, page_text):
    return "supported", "ok"


def _page_text_available(document_type, filename, page_number):
    return f"Texto de la página {page_number}"


class TestRunS3:
    @pytest.mark.asyncio
    async def test_all_supported_gives_faithfulness_1(self):
        golden = _golden(qa=[{"id": "q01", "question": "¿Presupuesto?"}] * 1)

        async def query_fn(question):
            return _response("Son 100.000 € [pcap p. 5].", [_citation(5)])

        result = await run_s3(
            golden, query_fn, _judge_always_supported, _page_text_available, NO_INFO, allow_draft=True
        )
        assert result.metrics["faithfulness"] == 1.0
        assert result.metrics["citations_judged"] == 1
        assert result.metrics["answered_without_citation"] == 0

    @pytest.mark.asyncio
    async def test_mixed_verdicts(self):
        golden = _golden(qa=[
            {"id": "q01", "question": "A"},
            {"id": "q02", "question": "B"},
        ])
        answers = {
            "A": _response("Respuesta A [pcap p. 1].", [_citation(1)]),
            "B": _response("Respuesta B [pcap p. 2].", [_citation(2)]),
        }

        async def query_fn(question):
            return answers[question]

        async def judge_fn(question, answer, doc_type, page, page_text):
            return ("supported", "ok") if page == 1 else ("not_supported", "no aparece")

        result = await run_s3(golden, query_fn, judge_fn, _page_text_available, NO_INFO, allow_draft=True)
        assert result.metrics["supported"] == 1
        assert result.metrics["not_supported"] == 1
        assert result.metrics["faithfulness"] == 0.5

    @pytest.mark.asyncio
    async def test_answered_without_citation_flagged(self):
        golden = _golden(qa=[{"id": "q01", "question": "A"}])

        async def query_fn(question):
            return _response("Afirmación sin ninguna cita.")

        result = await run_s3(
            golden, query_fn, _judge_always_supported, _page_text_available, NO_INFO, allow_draft=True
        )
        assert result.metrics["answered_without_citation"] == 1
        assert result.metrics["faithfulness"] is None

    @pytest.mark.asyncio
    async def test_refused_answerable_counted_not_judged(self):
        golden = _golden(qa=[{"id": "q01", "question": "A"}])

        async def query_fn(question):
            return _response(NO_INFO)

        result = await run_s3(
            golden, query_fn, _judge_always_supported, _page_text_available, NO_INFO, allow_draft=True
        )
        assert result.metrics["refused_answerable"] == 1
        assert result.metrics["citations_judged"] == 0

    @pytest.mark.asyncio
    async def test_page_text_unavailable_excluded_from_ratio(self):
        golden = _golden(qa=[{"id": "q01", "question": "A"}])

        async def query_fn(question):
            return _response("R [pcap p. 1] [pcap p. 2].", [_citation(1), _citation(2)])

        def page_text_fn(document_type, filename, page_number):
            return "texto" if page_number == 1 else None

        result = await run_s3(
            golden, query_fn, _judge_always_supported, page_text_fn, NO_INFO, allow_draft=True
        )
        assert result.metrics["page_text_unavailable"] == 1
        assert result.metrics["citations_judged"] == 1
        assert result.metrics["faithfulness"] == 1.0

    @pytest.mark.asyncio
    async def test_judge_parse_error_recorded(self):
        golden = _golden(qa=[{"id": "q01", "question": "A"}])

        async def query_fn(question):
            return _response("R [pcap p. 1].", [_citation(1)])

        async def judge_fn(question, answer, doc_type, page, page_text):
            raise JudgeParseError("salida no es JSON")

        result = await run_s3(golden, query_fn, judge_fn, _page_text_available, NO_INFO, allow_draft=True)
        assert result.metrics["judge_errors"] == 1
        assert result.metrics["faithfulness"] is None

    @pytest.mark.asyncio
    async def test_draft_rejected_without_flag(self):
        golden = _golden(status="draft")

        async def query_fn(question):
            return _response(NO_INFO)

        with pytest.raises(DraftDatasetError):
            await run_s3(
                golden, query_fn, _judge_always_supported, _page_text_available, NO_INFO
            )
        # Con allow_draft sí corre.
        result = await run_s3(
            golden, query_fn, _judge_always_supported, _page_text_available,
            NO_INFO, allow_draft=True,
        )
        assert result.metrics["questions"] == 10


class TestRunS4:
    @pytest.mark.asyncio
    async def test_canonical_refusal_counts_as_refused(self):
        golden = _golden(unanswerable=[{"id": "u01", "question": "¿ISO 27001?"}])

        async def query_fn(question):
            return _response(NO_INFO)

        result = await run_s4(golden, query_fn, NO_INFO, allow_draft=True)
        assert result.metrics["false_answers"] == 0
        assert result.metrics["refused"] == 1

    @pytest.mark.asyncio
    async def test_hedged_hallucination_containing_marker_is_false_answer(self):
        """Igualdad estricta con la constante canónica: una respuesta que CONTIENE el
        texto de rechazo pero añade contenido inventado debe contar como falsa
        (checklist spec 5.3 §8 — substring no vale)."""
        golden = _golden(unanswerable=[{"id": "u01", "question": "¿ISO 27001?"}])
        hedged = NO_INFO + " No obstante, probablemente se exige ISO 27001 [pcap p. 3]."

        async def query_fn(question):
            return _response(hedged)

        result = await run_s4(golden, query_fn, NO_INFO, allow_draft=True)
        assert result.metrics["false_answers"] == 1
        assert result.metrics["false_answer_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_uses_pipeline_canonical_constant(self):
        """La constante que cablea run.py es la del pipeline real — si cambia el texto
        del producto, este test recuerda que el harness la sigue automáticamente."""
        from app.services.query import _NO_INFO_ANSWER

        golden = _golden(unanswerable=[{"id": "u01", "question": "X"}])

        async def query_fn(question):
            return _response(_NO_INFO_ANSWER)

        result = await run_s4(golden, query_fn, _NO_INFO_ANSWER, allow_draft=True)
        assert result.metrics["false_answers"] == 0


class TestGate:
    def _s3(self, supported, not_supported, uncited=0):
        judged = supported + not_supported
        return S3Result(
            golden_key="g",
            items=[],
            metrics={
                "supported": supported,
                "not_supported": not_supported,
                "citations_judged": judged,
                "answered_without_citation": uncited,
            },
        )

    def _s4(self, false_answers, total=5):
        return S4Result(
            golden_key="g", items=[],
            metrics={"questions": total, "refused": total - false_answers,
                     "false_answers": false_answers},
        )

    def test_pass(self):
        gate = evaluate_gate([self._s3(20, 0)], [self._s4(0)])
        assert gate.passed
        assert gate.reasons == []

    def test_low_faithfulness_fails(self):
        gate = evaluate_gate([self._s3(18, 2)], [self._s4(0)])  # 0.90 < 0.95
        assert not gate.passed
        assert any("faithfulness" in r for r in gate.reasons)

    def test_false_answer_fails(self):
        gate = evaluate_gate([self._s3(20, 0)], [self._s4(1)])
        assert not gate.passed
        assert any("S4" in r for r in gate.reasons)

    def test_uncited_answer_fails(self):
        gate = evaluate_gate([self._s3(20, 0, uncited=1)], [self._s4(0)])
        assert not gate.passed
        assert any("sin cita" in r for r in gate.reasons)

    def test_zero_judged_citations_fails(self):
        gate = evaluate_gate([self._s3(0, 0)], [self._s4(0)])
        assert not gate.passed
        assert any("0 citas" in r for r in gate.reasons)

    def test_faithfulness_aggregated_not_averaged(self):
        """Agregado sobre todas las citas: 1/2 + 39/40 = 40/42 ≈ 0.952 → pasa,
        aunque la media de medias (0.74) suspendería."""
        gate = evaluate_gate([self._s3(1, 1), self._s3(39, 1)], [self._s4(0)])
        assert gate.passed

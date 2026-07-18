"""Tests del ensamblado de reportes, baseline y comparación de deltas."""

import json

from eval.report import (
    build_report,
    compare_with_baseline,
    load_baseline,
    render_markdown,
    write_report,
)
from eval.runner import (
    CitationJudgement,
    GateResult,
    S3ItemResult,
    S3Result,
    S4ItemResult,
    S4Result,
)


def _s3_result():
    item = S3ItemResult(
        qa_id="q01",
        question="¿Presupuesto?",
        answer="100.000 € [pcap p. 5]",
        answered=True,
        judgements=[CitationJudgement("pcap", 5, "supported", "ok")],
        latency_ms=1200,
        tokens_prompt=500,
        tokens_completion=80,
    )
    return S3Result(
        golden_key="test-pliego",
        items=[item],
        metrics={
            "questions": 1, "answered": 1, "refused_answerable": 0,
            "answered_without_citation": 0, "citations_judged": 1,
            "supported": 1, "not_supported": 0, "page_text_unavailable": 0,
            "judge_errors": 0, "faithfulness": 1.0,
        },
    )


def _s4_result(false_answers=0):
    items = [
        S4ItemResult("u01", "¿ISO 27001?", "No he encontrado información...",
                     refused=false_answers == 0, latency_ms=800),
    ]
    return S4Result(
        golden_key="test-pliego",
        items=items,
        metrics={"questions": 1, "refused": 1 - false_answers,
                 "false_answers": false_answers,
                 "false_answer_rate": float(false_answers)},
    )


def _meta():
    return {
        "suite": "all",
        "git_sha": "abc1234",
        "judge_versions": {"faithfulness": "1.0"},
        "dataset_versions": {"test-pliego": 1},
        "model_deployments": {"judge": "chat_pliego_4o"},
        "_judge_tokens_prompt": 300,
        "_judge_tokens_completion": 40,
    }


class TestBuildReport:
    def test_aggregates_and_meta(self):
        report = build_report(
            [_s3_result()], [_s4_result()], GateResult(True, []), _meta()
        )
        assert report["aggregate"]["faithfulness"] == 1.0
        assert report["aggregate"]["false_answer_rate"] == 0.0
        # Tokens del pipeline + tokens del juez.
        assert report["meta"]["tokens_prompt"] == 800
        assert report["meta"]["tokens_completion"] == 120
        assert report["meta"]["latency_p50_ms"] == 1000
        assert report["gate"]["passed"] is True


class TestBaselineComparison:
    def test_no_baseline_not_comparable(self):
        report = build_report([_s3_result()], [_s4_result()], GateResult(True, []), _meta())
        cmp = compare_with_baseline(report, None)
        assert cmp["comparable"] is False

    def test_same_versions_comparable_with_deltas(self):
        report = build_report([_s3_result()], [_s4_result()], GateResult(True, []), _meta())
        baseline = json.loads(json.dumps(report))
        baseline["aggregate"]["faithfulness"] = 0.9
        cmp = compare_with_baseline(report, baseline)
        assert cmp["comparable"] is True
        assert cmp["deltas"]["faithfulness"]["delta"] == 0.1

    def test_judge_version_change_invalidates_baseline(self):
        report = build_report([_s3_result()], [_s4_result()], GateResult(True, []), _meta())
        baseline = json.loads(json.dumps(report))
        baseline["meta"]["judge_versions"] = {"faithfulness": "0.9"}
        cmp = compare_with_baseline(report, baseline)
        assert cmp["comparable"] is False
        assert "re-baselinear" in cmp["reason"]


class TestWriteReport:
    def test_writes_json_md_and_baseline(self, tmp_path):
        eval_dir = tmp_path / "eval"
        reports_dir = eval_dir / "reports"
        report = build_report(
            [_s3_result()], [_s4_result()], GateResult(True, []), _meta()
        )
        cmp = compare_with_baseline(report, None)
        json_path, md_path = write_report(report, cmp, reports_dir, as_baseline=True)

        assert json_path.is_file() and md_path.is_file()
        assert load_baseline(eval_dir) is not None
        md = md_path.read_text(encoding="utf-8")
        assert "PASA" in md
        assert "test-pliego" in md

    def test_markdown_lists_failures(self):
        s4 = _s4_result(false_answers=1)
        s4.items[0].refused = False
        s4.items[0].answer = "Sí, exige ISO 27001 [pcap p. 3]."
        gate = GateResult(False, ["S4: 1 respuesta(s) falsa(s)"])
        report = build_report([_s3_result()], [s4], gate, _meta())
        md = render_markdown(report, {"comparable": False, "reason": "sin baseline"})
        assert "FALLA" in md
        assert "NO rechazada" in md
        assert "ISO 27001" in md

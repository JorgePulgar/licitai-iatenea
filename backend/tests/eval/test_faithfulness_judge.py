"""Tests del juez de fidelidad S3: construcción de mensajes y parseo de veredictos."""

import pytest

from eval.judges.faithfulness import (
    FAITHFULNESS_JUDGE_PROMPT,
    FAITHFULNESS_JUDGE_VERSION,
    JudgeParseError,
    build_judge_messages,
    parse_faithfulness_verdict,
)


class TestBuildMessages:
    def test_structure_and_content(self):
        messages = build_judge_messages(
            question="¿Cuál es el presupuesto?",
            answer="El presupuesto es 100.000 € [pcap p. 5].",
            document_type="pcap",
            page_number=5,
            page_text="El presupuesto base de licitación asciende a 100.000 euros.",
        )
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == FAITHFULNESS_JUDGE_PROMPT
        user = messages[1]["content"]
        assert "¿Cuál es el presupuesto?" in user
        assert "[pcap p. 5]" in user
        assert "<pagina>" in user and "</pagina>" in user
        assert "100.000 euros" in user

    def test_prompt_is_versioned(self):
        assert FAITHFULNESS_JUDGE_VERSION == "1.0"
        # El prompt exige salida JSON y contempla equivalencia de formatos numéricos.
        assert "JSON" in FAITHFULNESS_JUDGE_PROMPT
        assert "1.234.567,89" in FAITHFULNESS_JUDGE_PROMPT


class TestParseVerdict:
    def test_supported(self):
        verdict, rationale = parse_faithfulness_verdict(
            '{"verdict": "supported", "rationale": "El importe aparece literal."}'
        )
        assert verdict == "supported"
        assert rationale == "El importe aparece literal."

    def test_not_supported(self):
        verdict, _ = parse_faithfulness_verdict('{"verdict": "not_supported", "rationale": "x"}')
        assert verdict == "not_supported"

    def test_missing_rationale_tolerated(self):
        verdict, rationale = parse_faithfulness_verdict('{"verdict": "supported"}')
        assert verdict == "supported"
        assert rationale == ""

    def test_invalid_verdict_raises(self):
        with pytest.raises(JudgeParseError, match="inválido"):
            parse_faithfulness_verdict('{"verdict": "maybe", "rationale": "x"}')

    def test_non_json_raises(self):
        with pytest.raises(JudgeParseError, match="no es JSON"):
            parse_faithfulness_verdict("La cita parece correcta.")

    def test_json_array_raises(self):
        with pytest.raises(JudgeParseError, match="objeto"):
            parse_faithfulness_verdict('["supported"]')

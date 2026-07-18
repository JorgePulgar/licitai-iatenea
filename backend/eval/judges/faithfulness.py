"""Juez de fidelidad (suite S3, spec 5.3 §2-3).

Qué hace: dada una respuesta del chatbot con una cita concreta ``[doc p. N]``,
y el texto REAL de esa página del PDF (no los chunks recuperados — checklist
spec 5.3 §8), decide si la página respalda lo que la respuesta le atribuye.

Input: pregunta, respuesta completa, cita evaluada (doc + página), texto de página.
Output: JSON ``{"verdict": "supported"|"not_supported", "rationale": "<una línea>"}``.
Llamada: temperature 0, response_format json_object, deployment EVAL_JUDGE_MODEL.

Un cambio en este prompt ⇒ subir FAITHFULNESS_JUDGE_VERSION ⇒ invalida baselines.
"""

import json

FAITHFULNESS_JUDGE_VERSION = "1.0"

# v1.0 — 2026-07-18: primera versión (DM9). Veredicto binario + rationale de una línea.
FAITHFULNESS_JUDGE_PROMPT = """Eres un evaluador estricto de fidelidad de citas para un asistente de licitaciones públicas españolas.

Recibirás:
1. La PREGUNTA del usuario.
2. La RESPUESTA completa del asistente, que contiene citas inline con formato [doc p. N].
3. La CITA concreta que debes evaluar (tipo de documento y número de página).
4. El TEXTO REAL de esa página del pliego.

Tu tarea: decidir si el texto real de la página respalda las afirmaciones que la respuesta atribuye a ESA cita concreta. Ignora las partes de la respuesta atribuidas a otras páginas.

Reglas:
- "supported": todas las afirmaciones atribuidas a esa página aparecen en su texto o se deducen directamente de él.
- "not_supported": alguna afirmación atribuida a esa página no aparece en su texto, lo contradice, o la página trata de otra cosa.
- Diferencias de formato NO cuentan como fallo: "1.234.567,89 €" y "1234567.89 EUR" son el mismo importe; mayúsculas, tildes y orden de palabras son irrelevantes.
- Datos numéricos (importes, plazos, fechas, porcentajes) deben coincidir en valor. Un número distinto = "not_supported".
- Si el texto de la página está vacío o es ilegible, responde "not_supported" y dilo en el rationale.
- Sé estricto: ante la duda de si la página respalda una afirmación, es "not_supported".

Responde SOLO con un objeto JSON, sin texto adicional:
{"verdict": "supported" | "not_supported", "rationale": "<justificación en una línea>"}"""

VALID_VERDICTS = {"supported", "not_supported"}


class JudgeParseError(ValueError):
    """La salida del juez no es el JSON esperado."""


def build_judge_messages(
    question: str,
    answer: str,
    document_type: str,
    page_number: int,
    page_text: str,
) -> list[dict[str, str]]:
    """Construye los mensajes para la llamada al juez de fidelidad."""
    user_message = (
        f"PREGUNTA:\n{question}\n\n"
        f"RESPUESTA:\n{answer}\n\n"
        f"CITA A EVALUAR: [{document_type} p. {page_number}]\n\n"
        f"TEXTO REAL DE LA PÁGINA {page_number} ({document_type}):\n"
        f"<pagina>\n{page_text}\n</pagina>"
    )
    return [
        {"role": "system", "content": FAITHFULNESS_JUDGE_PROMPT},
        {"role": "user", "content": user_message},
    ]


def parse_faithfulness_verdict(raw: str) -> tuple[str, str]:
    """Parsea la salida del juez → (verdict, rationale). Lanza JudgeParseError."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JudgeParseError(f"salida del juez no es JSON: {raw[:200]!r}") from e
    if not isinstance(data, dict):
        raise JudgeParseError(f"salida del juez no es un objeto JSON: {raw[:200]!r}")

    verdict = data.get("verdict")
    if verdict not in VALID_VERDICTS:
        raise JudgeParseError(
            f"verdict '{verdict}' inválido; debe ser uno de {sorted(VALID_VERDICTS)}"
        )
    rationale = str(data.get("rationale") or "").strip()
    return verdict, rationale

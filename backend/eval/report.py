"""Reportes del harness de evaluación: JSON + Markdown, baseline y deltas (spec 5.3 §4).

- Cada run escribe ``eval/reports/<fecha>-<git-sha>.json`` y ``.md``.
- ``--baseline`` estampa el run como baseline (``eval/baseline.json``) — acto
  deliberado; el modo por defecto compara contra el baseline vigente.
- Un cambio de juez o de dataset_version invalida el baseline: el delta solo se
  muestra si versiones coinciden; si no, se avisa de re-baselinear.
"""

import json
import statistics
import subprocess
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from eval.runner import GateResult, S3Result, S4Result

BASELINE_FILENAME = "baseline.json"

# Métricas de cabecera comparadas contra baseline.
HEADLINE_METRICS = ("faithfulness", "false_answer_rate")


def git_sha(repo_dir: Path | None = None) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=repo_dir,
        ).stdout.strip()
    except Exception:
        return "no-git"


def _latencies(s3_results: list[S3Result], s4_results: list[S4Result]) -> list[int]:
    lats = [it.latency_ms for r in s3_results for it in r.items]
    lats += [it.latency_ms for r in s4_results for it in r.items]
    return lats


def build_report(
    s3_results: list[S3Result],
    s4_results: list[S4Result],
    gate: GateResult,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """Ensambla el reporte completo (serializable a JSON)."""
    lats = _latencies(s3_results, s4_results)
    tokens_prompt = sum(
        it.tokens_prompt or 0 for r in s3_results for it in r.items
    ) + meta.pop("_judge_tokens_prompt", 0)
    tokens_completion = sum(
        it.tokens_completion or 0 for r in s3_results for it in r.items
    ) + meta.pop("_judge_tokens_completion", 0)

    judged = sum(r.metrics["citations_judged"] for r in s3_results)
    supported = sum(r.metrics["supported"] for r in s3_results)
    s4_total = sum(r.metrics["questions"] for r in s4_results)
    s4_false = sum(r.metrics["false_answers"] for r in s4_results)

    return {
        "meta": {
            **meta,
            "date": date.today().isoformat(),
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "latency_p50_ms": int(statistics.median(lats)) if lats else None,
            "latency_p95_ms": int(
                statistics.quantiles(lats, n=20)[18]) if len(lats) >= 2 else (lats[0] if lats else None),
        },
        "aggregate": {
            "faithfulness": round(supported / judged, 4) if judged else None,
            "false_answer_rate": round(s4_false / s4_total, 4) if s4_total else None,
        },
        "gate": {"passed": gate.passed, "reasons": gate.reasons},
        "s3": [{"golden_key": r.golden_key, "metrics": r.metrics,
                "items": [asdict(it) for it in r.items]} for r in s3_results],
        "s4": [{"golden_key": r.golden_key, "metrics": r.metrics,
                "items": [asdict(it) for it in r.items]} for r in s4_results],
    }


def compare_with_baseline(report: dict[str, Any], baseline: dict[str, Any] | None) -> dict[str, Any]:
    """Deltas de métricas de cabecera vs baseline; None si no hay baseline comparable."""
    if baseline is None:
        return {"comparable": False, "reason": "sin baseline — usa --baseline para estampar uno"}
    same_versions = (
        baseline.get("meta", {}).get("judge_versions") == report["meta"].get("judge_versions")
        and baseline.get("meta", {}).get("dataset_versions") == report["meta"].get("dataset_versions")
    )
    if not same_versions:
        return {
            "comparable": False,
            "reason": "versiones de juez/dataset distintas al baseline — re-baselinear, nunca mezclar",
        }
    deltas = {}
    for metric in HEADLINE_METRICS:
        current = report["aggregate"].get(metric)
        base = baseline.get("aggregate", {}).get(metric)
        deltas[metric] = {
            "current": current,
            "baseline": base,
            "delta": round(current - base, 4) if current is not None and base is not None else None,
        }
    return {"comparable": True, "deltas": deltas}


def render_markdown(report: dict[str, Any], comparison: dict[str, Any]) -> str:
    meta = report["meta"]
    agg = report["aggregate"]
    gate = report["gate"]
    lines = [
        f"# Eval-lite — {meta['date']} — `{meta.get('git_sha', '?')}`",
        "",
        f"**Gate: {'✅ PASA' if gate['passed'] else '❌ FALLA'}**",
    ]
    for reason in gate["reasons"]:
        lines.append(f"- ❌ {reason}")
    lines += [
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Faithfulness (S3, agregada) | {agg['faithfulness']} |",
        f"| Tasa de respuestas falsas (S4) | {agg['false_answer_rate']} |",
        f"| Tokens (prompt / completion) | {meta['tokens_prompt']} / {meta['tokens_completion']} |",
        f"| Latencia p50 / p95 (ms) | {meta['latency_p50_ms']} / {meta['latency_p95_ms']} |",
        f"| Versión juez faithfulness | {meta.get('judge_versions', {}).get('faithfulness', '?')} |",
        f"| Versiones dataset | {meta.get('dataset_versions', {})} |",
        f"| Deployments | {meta.get('model_deployments', {})} |",
        "",
    ]

    if comparison.get("comparable"):
        lines += ["## Delta vs baseline", "", "| Métrica | Actual | Baseline | Δ |", "|---|---|---|---|"]
        for metric, d in comparison["deltas"].items():
            lines.append(f"| {metric} | {d['current']} | {d['baseline']} | {d['delta']} |")
        lines.append("")
    else:
        lines += [f"> Baseline no comparable: {comparison.get('reason')}", ""]

    for suite_key, title in (("s3", "S3 — Faithfulness"), ("s4", "S4 — Refusal")):
        lines += [f"## {title}", ""]
        for suite in report[suite_key]:
            lines.append(f"### `{suite['golden_key']}`")
            lines.append("")
            lines.append("| Métrica | Valor |")
            lines.append("|---|---|")
            for k, v in suite["metrics"].items():
                lines.append(f"| {k} | {v} |")
            lines.append("")
            failures = _suite_failures(suite_key, suite)
            if failures:
                lines.append("**Fallos:**")
                lines.append("")
                lines.extend(failures)
                lines.append("")
    return "\n".join(lines)


def _suite_failures(suite_key: str, suite: dict[str, Any]) -> list[str]:
    out = []
    if suite_key == "s3":
        for it in suite["items"]:
            if it["answered"] and not it["judgements"]:
                out.append(f"- `{it['qa_id']}` respondida SIN citas: _{it['question']}_")
            for j in it["judgements"]:
                if j["verdict"] != "supported":
                    out.append(
                        f"- `{it['qa_id']}` [{j['document_type']} p. {j['page_number']}] "
                        f"→ **{j['verdict']}** — {j['rationale']}"
                    )
    else:
        for it in suite["items"]:
            if not it["refused"]:
                out.append(
                    f"- `{it['item_id']}` NO rechazada: _{it['question']}_ → «{it['answer'][:160]}»"
                )
    return out


def load_baseline(eval_dir: Path) -> dict[str, Any] | None:
    path = eval_dir / BASELINE_FILENAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(
    report: dict[str, Any],
    comparison: dict[str, Any],
    reports_dir: Path,
    as_baseline: bool = False,
) -> tuple[Path, Path]:
    """Escribe JSON + MD en reports/; con as_baseline, estampa también baseline.json."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['meta']['date']}-{report['meta'].get('git_sha', 'no-git')}"
    json_path = reports_dir / f"{stem}.json"
    md_path = reports_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(report, comparison), encoding="utf-8")
    if as_baseline:
        (reports_dir.parent / BASELINE_FILENAME).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return json_path, md_path

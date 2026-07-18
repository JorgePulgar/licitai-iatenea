"""CLI del harness de evaluación — cablea el pipeline RAG real (requiere Azure).

Uso (desde backend/, con .env con credenciales):
    python -m eval.run --suite all --map mentorias-turismo=<licitacion_id> [--map ...]
    python -m eval.run --suite s4 --map obras-alcorcon-2026=<id> --allow-draft
    python -m eval.run --suite all --map ... --baseline   # estampa nuevo baseline

- ``--map key=licitacion_id`` liga cada fichero golden a la licitación ya
  indexada en el entorno (los IDs son por-entorno; no se versionan).
- Exit code 0 si el gate DM9 pasa (faithfulness ≥ 0.95, respuestas falsas = 0),
  1 si falla. Reporte JSON+MD en ``eval/reports/``.
- ``--baseline`` exige working tree limpio (spec 5.3 §8): el baseline debe
  corresponder a un commit reproducible.
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

EVAL_DIR = BACKEND_DIR / "eval"
GOLDEN_DIR = EVAL_DIR / "golden"
REPORTS_DIR = EVAL_DIR / "reports"
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures" / "pliegos"

# Deployment del juez (spec 5.3 §3: calidad importa, volumen pequeño).
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "chat_pliego_4o")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Eval-lite DM9: suites S3 + S4")
    parser.add_argument("--suite", choices=["s3", "s4", "all"], default="all")
    parser.add_argument(
        "--map", action="append", default=[], metavar="KEY=LICITACION_ID",
        help="liga un golden key a una licitación indexada (repetible)",
    )
    parser.add_argument("--baseline", action="store_true",
                        help="estampa este run como nuevo baseline (exige git limpio)")
    parser.add_argument("--allow-draft", action="store_true",
                        help="permite datasets en status draft (solo smoke, nunca baseline)")
    return parser.parse_args()


def _parse_map(pairs: list[str]) -> dict[str, str]:
    mapping = {}
    for pair in pairs:
        if "=" not in pair:
            sys.exit(f"--map inválido: '{pair}' (formato KEY=LICITACION_ID)")
        key, lic_id = pair.split("=", 1)
        mapping[key.strip()] = lic_id.strip()
    return mapping


def _require_clean_tree() -> None:
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=BACKEND_DIR,
    ).stdout.strip()
    if dirty:
        sys.exit("--baseline exige working tree limpio (el baseline debe ser reproducible).")


async def _main() -> int:
    args = _parse_args()
    if args.baseline and args.allow_draft:
        sys.exit("--baseline con --allow-draft no tiene sentido: un draft no baselinea.")
    if args.baseline:
        _require_clean_tree()

    # Imports diferidos: cargan settings (Key Vault) y SDKs de Azure.
    from sqlalchemy.orm import selectinload

    from app.db.database import SessionLocal
    from app.models.domain import Licitacion
    from app.services.embeddings import get_openai_client
    from app.services.query import _NO_INFO_ANSWER, query_licitacion

    from eval import report as report_mod
    from eval import runner
    from eval.judges.faithfulness import (
        FAITHFULNESS_JUDGE_VERSION,
        build_judge_messages,
        parse_faithfulness_verdict,
    )
    from eval.pages import FixturePageTextProvider
    from eval.schema import load_all_golden

    mapping = _parse_map(args.map)
    datasets = [d for d in load_all_golden(GOLDEN_DIR) if d.key in mapping]
    if not datasets:
        sys.exit(
            f"Ningún golden mapeado. Keys disponibles: "
            f"{[d.key for d in load_all_golden(GOLDEN_DIR)]}. Usa --map KEY=LICITACION_ID."
        )

    client = get_openai_client()
    if client is None:
        sys.exit("Azure OpenAI no configurado — el harness necesita credenciales (.env).")

    judge_tokens = {"prompt": 0, "completion": 0}

    async def judge_fn(question, answer, document_type, page_number, page_text):
        response = await client.chat.completions.create(
            model=JUDGE_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=build_judge_messages(
                question, answer, document_type, page_number, page_text
            ),
        )
        usage = getattr(response, "usage", None)
        judge_tokens["prompt"] += getattr(usage, "prompt_tokens", 0) or 0
        judge_tokens["completion"] += getattr(usage, "completion_tokens", 0) or 0
        return parse_faithfulness_verdict(response.choices[0].message.content or "")

    s3_results: list[runner.S3Result] = []
    s4_results: list[runner.S4Result] = []

    db = SessionLocal()
    try:
        for golden in datasets:
            lic_id = mapping[golden.key]
            lic = (
                db.query(Licitacion)
                .options(selectinload(Licitacion.documents))
                .filter(Licitacion.id == lic_id)
                .first()
            )
            if lic is None:
                sys.exit(f"Licitación '{lic_id}' (golden '{golden.key}') no existe en la BD.")

            page_counts = {
                p.id: p.page_count for p in lic.documents if p.page_count is not None
            }

            async def query_fn(question: str, _lic=lic, _pages=page_counts):
                return await query_licitacion(
                    question=question,
                    licitacion_id=_lic.id,
                    user_id=_lic.user_id,
                    title=_lic.title,
                    page_counts=_pages,
                )

            provider = FixturePageTextProvider(
                {d.document_type: FIXTURES_DIR / d.filename for d in golden.documents}
            )

            print(f"● {golden.key} → {lic.title or lic.id}")
            if args.suite in ("s3", "all"):
                r3 = await runner.run_s3(
                    golden, query_fn, judge_fn, provider.get,
                    _NO_INFO_ANSWER, allow_draft=args.allow_draft,
                )
                s3_results.append(r3)
                print(f"  S3: {r3.metrics}")
            if args.suite in ("s4", "all"):
                r4 = await runner.run_s4(
                    golden, query_fn, _NO_INFO_ANSWER, allow_draft=args.allow_draft,
                )
                s4_results.append(r4)
                print(f"  S4: {r4.metrics}")
    finally:
        db.close()

    gate = runner.evaluate_gate(s3_results, s4_results)
    meta = {
        "suite": args.suite,
        "git_sha": report_mod.git_sha(BACKEND_DIR),
        "judge_versions": {"faithfulness": FAITHFULNESS_JUDGE_VERSION},
        "dataset_versions": {d.key: d.dataset_version for d in datasets},
        "model_deployments": {"judge": JUDGE_MODEL},
        "_judge_tokens_prompt": judge_tokens["prompt"],
        "_judge_tokens_completion": judge_tokens["completion"],
    }
    full_report = report_mod.build_report(s3_results, s4_results, gate, meta)
    baseline = report_mod.load_baseline(EVAL_DIR)
    comparison = report_mod.compare_with_baseline(full_report, baseline)
    json_path, md_path = report_mod.write_report(
        full_report, comparison, REPORTS_DIR, as_baseline=args.baseline,
    )

    print(f"\nReporte: {md_path}")
    if args.baseline:
        print(f"Baseline estampado: {EVAL_DIR / report_mod.BASELINE_FILENAME} "
              f"(dataset {meta['dataset_versions']}, juez {meta['judge_versions']})")
    print(f"Gate: {'PASA' if gate.passed else 'FALLA'}")
    for reason in gate.reasons:
        print(f"  ✗ {reason}")
    return 0 if gate.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))

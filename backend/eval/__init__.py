"""Harness de evaluación RAG (spec 5.3, subset DM9: suites S3 faithfulness + S4 refusal).

Estructura:
    eval/golden/    — golden dataset etiquetado a mano (YAML, versionado)
    eval/judges/    — prompts de jueces LLM (versionados como prompts de producto)
    eval/schema.py  — modelos Pydantic + carga/validación del golden
    eval/pages.py   — texto real por página desde los PDF fixture (pypdf)
    eval/runner.py  — lógica pura de las suites (inyectable, testeable offline)
    eval/report.py  — reportes JSON+Markdown, baseline y deltas
    eval/run.py     — CLI que cablea el pipeline real (requiere Azure)

Ejecución (desde backend/, con .env con credenciales Azure):
    python -m eval.run --suite all --map <golden_key>=<licitacion_id>
"""

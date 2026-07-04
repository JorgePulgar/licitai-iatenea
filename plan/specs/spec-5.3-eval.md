# Spec 5.3 — RAG evaluation harness (quality gate + model-swap reports)

> Fable-written spec, 2026-07-04. Implementer: Opus 4.8 (judge prompts, harness core), Sonnet 5 (runner plumbing, CI). Review checklist at end.
> Extends task 5.3 and replaces the ad-hoc `scripts/eval_rag.py` (keep it until parity). Current script measures **traceability only** (answered + cited pages exist). This spec adds correctness, faithfulness, refusal, requirements recall, memoria quality, injection resistance — and makes them a **regression gate**: every prompt/model/retrieval change runs against a fixed baseline and fails on regression.
> Commercial stake: "sin cita, sin afirmación" is the sales promise (claude.md §8) — this harness is what makes it a measured number instead of a slogan. Publishable metrics feed the sales page.

## 1. Golden dataset (the one manual investment)

- **Corpus**: 4 existing fixture pliegos (`tests/fixtures/pliegos/`) + [3–4] more chosen for variety (obra/servicio/suministro, con y sin lotes, escaneado-OCR y nativo). All are public documents — fine to commit.
- **Per pliego, hand-labeled by Jorge (one-time, ~2h each):** stored as `eval/golden/<pliego>.yaml`:
  - `qa`: 15–25 extractive questions → expected answer (normalized value where numeric: importe, plazo, fechas) + expected page(s).
  - `unanswerable`: 5 questions whose answer is NOT in the pliego (plausible ones — "¿exige ISO 27001?" when it doesn't).
  - `requirements`: the full labeled checklist (or minimum: all `obligatorio` items) with category + page.
  - `facts`: presupuesto base, plazo ejecución, plazo presentación, criterios weights — the fields Summary must nail.
- Dataset is **versioned**; any label change = dataset version bump = new baseline required.

## 2. Metric suites

| Suite | What | How | Cost |
|---|---|---|---|
| **S1 retrieval** | hit@k (ground-truth page in retrieved set), MRR | pure Search calls | ~0 € |
| **S2 answers** | correctness on `qa` | numeric/date fields: normalize + exact match. Free text: LLM-judge (rubric: correct / partial / wrong) | LLM |
| **S3 faithfulness** | every citation in every answer: does the cited page's actual text support the claim? | LLM-judge given (claim, page text) → supported/not. **The headline metric** | LLM |
| **S4 refusal** | `unanswerable` set → must return the no-info answer | string match on `_NO_INFO_ANSWER` path | LLM (pipeline) |
| **S5 requirements** | recall/precision vs labeled checklist; obligatorio-classification accuracy; page validity | set matching (fuzzy title match) + judge for borderline | LLM |
| **S6 memoria** | draft quality on [2] pliegos with company-profile fixture | hard checks (follows PPT esquema section-for-section; zero capabilities absent from the profile fixture = fabrication check) + judge rubric 1–5 (coverage of requirements, coherence, tone) | LLM, heavier |
| **S7 injection** | resistance to the `prompts-hardened.md` attack suite | run existing injection tests through the live pipeline → resistance rate | LLM |
| **meta** | tokens + € per run, latency p50/p95 per endpoint | logged on every run | — |

## 3. Judge design (the part that goes wrong silently)

- Judge model: `chat-heavy` deployment (quality matters; volume is small). Judge prompts live in `eval/judges/*.py`, **versioned like product prompts** (claude.md §8).
- Judge output: verdict + one-line rationale, JSON-forced. Rationales stored in the report (auditable).
- **Calibration**: first run → Jorge reviews [30] random judge verdicts; disagreement >10% → fix rubric before trusting the harness. Re-calibrate on judge-prompt or judge-model change.
- A judge change **invalidates baselines** (scores not comparable) → re-baseline, never mix.

## 4. Runner & reports

```
backend/eval/
├── golden/<pliego>.yaml       # dataset (versioned)
├── judges/*.py                # judge prompts
├── run.py                     # python -m eval.run --suite all|s1..s7 [--pliego X] [--baseline]
└── reports/<date>-<git-sha>.json + .md
```

- Report: per-suite scores, per-item failures (question, got, expected, judge rationale), cost, latency, dataset+judge versions, git SHA, model deployments used.
- `--baseline` stamps the run as the new baseline (deliberate act, reviewed). Comparison mode is default: report shows delta vs current baseline.
- `--compare` mode (task 5.3's model-swap use case): run suite twice with two model configs → side-by-side markdown. Model deployment names come from config (5.3's no-hardcoded-models rule).

## 5. Thresholds & gating

- **Process, not magic numbers**: first calibrated run = baseline; thresholds = baseline − tolerance. Starting tolerances (adjust after baseline): S3 faithfulness **≥ 0.95 absolute floor**, S4 false-answer rate **= 0 absolute**, S5 obligatorio-recall ≥ 0.90, S1 hit@5 ≥ 0.85, others −3 pts vs baseline.
- **CI**: S1 (free) on every backend PR. Full suite: manual `workflow_dispatch` + **required** before merging changes to `prompts/`, `services/{query,requirements,memoria,summary}.py`, retrieval config, or model deployments. Fail = red check with the delta table in the job summary.
- Full-run cost target: ≤ [5] € — if exceeded, trim qa set per pliego, don't skip suites.

## 6. Sales tie-in

After each baseline: export one-liner metrics (faithfulness %, refusal correctness, requirements recall, N real pliegos) → `sales-assets` trust section and demo talking points. Numbers beat adjectives with this buyer.

## 7. Acceptance

1. Golden dataset ≥ 5 pliegos labeled, schema-validated.
2. Full run produces report with all suites + cost + latency; re-run without changes → scores identical (±judge noise ≤2 pts, temperature 0 on judges).
3. Deliberate sabotage test: degrade a prompt (remove citation instruction) → S3 drops, gate fails. Restore → passes.
4. `--compare` on two chat models → side-by-side report.
5. Judge calibration session done, disagreement documented <10%.
6. CI wiring: PR touching `prompts/` without a green full run cannot merge.

## 8. Opus review checklist

- [ ] Judges: temperature 0, JSON-schema-forced output, versioned, rationale captured.
- [ ] Numeric answer matching normalizes formats (1.234.567,89 € vs 1234567.89) before comparing — no false fails on formatting.
- [ ] S3 judges against the **actual page text** from the doc, not against retrieved chunks (that would test retrieval twice and faithfulness never).
- [ ] Refusal check matches the canonical no-info constant, not a substring that a hedged hallucination could contain.
- [ ] Baseline files immutable in git; `--baseline` requires clean working tree + prints dataset/judge versions.
- [ ] Eval runs against a dedicated eval org/tenant (spec-2.2b) — never against client data.
- [ ] Cost meter actually sums all LLM calls including judges.
- [ ] `eval_rag.py` retired only after acceptance 1–6 pass (parity note in the PR).

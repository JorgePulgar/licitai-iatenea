# Spec 5.1 — PLACSP data layer (URL import · Radar · GTM prospect DB)

> Fable-written spec, 2026-07-04. Implementers: Opus 4.8 (parser core, Radar), Sonnet 5 (sync jobs, exports). Review checklist at end.
> One parser core, three consumers: (A) URL import (task 5.1-A), (B) Radar watchlist alerts (5.1-B, the retention feature), (C) **GTM prospect DB — needed in weeks, long before Phase 5**. Design is standalone-first so C runs without the product.

## 1. Sources (contrataciondelestado.es open data)

- **Sindicación ATOM feeds**: `licitacionesPerfilesContratanteCompleto3` — current feed + monthly ZIP archives (years back). Each ATOM entry embeds a **CODICE 2.x XML** (UBL dialect) contract notice.
- **Aggregated feed**: `PlataformasAgregadasSinMenores` — tenders from CCAA/local platforms (Cataluña, Euskadi…) that don't publish natively on PLACSP. Ingest BOTH; source tag per row.
- Dataset is listed on datos.gob.es — reuse permitted under Spanish open-data law (Ley 37/2007); attribute the source; do not re-publish raw dumps.
- **Entry lifecycle**: the same expediente re-appears across states (anuncio previa → licitación → adjudicación → formalización → anulación/desistimiento, plus corrections). Entries carry `updated` timestamps. **Dedupe key: expediente + órgano; keep latest version per state; corrections overwrite.**
- **What is NOT in the data (honesty constraints — these bound the GTM promises):**
  - Losing bidders' identities: NOT published structurally. Only adjudicatario (winner) + `número de ofertas recibidas`.
  - Consequence: "frequent losers" prospect filter is NOT derivable. Usable signals: frequent winners, lapsed winners, new entrants, competition density (`num_ofertas` by CPV/órgano).
  - Pliego documents are URLs in the XML, not embedded; some link to viewers rather than files.

## 2. Parser core (`placsp_core` — pure Python package, zero product deps)

- lxml + explicit XPath map for CODICE namespaces (they're versioned and ugly — one table in code mapping field → XPath list, tried in order).
- Input: ATOM file or ZIP; output: typed records (dataclasses): `Tender`, `Award`, `Organo`, `DocLink`.
- Must tolerate: missing fields (everything optional except expediente+órgano), multi-lot tenders (one Award per lot), encoding quirks, duplicated entries.
- Parser is versioned (`PARSER_VERSION` constant stored per row) → re-parse on upgrade is a WHERE clause, not a guess.
- **Home**: lives in the Iatenea internal-ops repo (GTM runs first); vendored into `licitai-iatenea` backend at Phase 5 (small, stable package — copy beats premature shared-lib infra). Single source of truth = ops repo until then.

## 3. Schema (engine-agnostic: DuckDB for standalone GTM, Azure SQL inside the product)

```
organos:   id, nombre, tipo (AGE|CCAA|local|otros), fuente
tenders:   expediente+organo_id (uk), titulo, cpv_codes (json/csv), importe_sin_iva,
           procedimiento, estado, plazo_presentacion, fecha_publicacion, url_perfil,
           doc_links (json: tipo→url), fuente_feed, parser_version, updated_at
awards:    tender_id, lote, adjudicatario_nif, adjudicatario_nombre,
           importe_adjudicacion, num_ofertas, fecha_adjudicacion
companies: nif (pk), nombre_normalizado, primera_vez, es_persona_fisica (bool)
```

Derived views (SQL, not tables): `company_activity` (awards 24m, CPV families, órganos, avg importe, avg num_ofertas faced), `cpv_competition` (avg bidders by CPV — feeds future pricing-intel M2 and content marketing stats).

**GDPR rule**: NIF pattern distinguishes personas jurídicas (CIF: letter-first) from personas físicas (DNI/NIE). `es_persona_fisica = true` rows are **excluded from all GTM exports and prospect scoring** — company data only, no personal-data processing for marketing.

## 4. Ingestion jobs

- **Backfill**: monthly ZIPs, last 24–36 months (≈170k tenders/year — few GB total, hours not days). Idempotent upserts.
- **Incremental**: current feed every 6–12 h (feed paginates via `next` links — follow until known-entry overlap). Alert if feed age > 48 h (staleness monitor).
- Standalone runner: `python -m placsp_core.sync --db placsp.duckdb [--backfill 2024-01]`. In-product (Phase 5): same logic on the 4.1 worker, cron-style queue message.

## 5. Consumer A — URL import (product task 5.1-A)

Paste expediente URL → resolve to feed entry / detail data → download PCAP+PPT+anexos → create licitación (org-scoped) → pipeline indexes.
- **SSRF guard (ties to finding 1b)**: download only from an allowlist of hosts (contrataciondelestado.es + known CCAA platform domains table); content-type + size limits (reuse spec-1.1 §3 validation); reject viewer links with a clear "download manually" message rather than scraping viewers in v1.
- Acceptance: URL in → indexed licitación, zero manual uploads; non-allowlisted URL → 422.

## 6. Consumer B — Radar (product task 5.1-B, retention feature)

- Per-org watchlist config: CPV prefixes, importe min/max, órgano/geo filter, min days-to-deadline.
- Daily: new tenders → filter → for top candidates (cap N/day/org) fetch pliego + run existing match-score service against the org corpus → digest email (task 3.2 email infra) with score + link to one-click import (Consumer A).
- **Cost control**: match-score only the filtered cap, never the firehose; quota-metered per spec-2.2b §5.
- Acceptance: seeded watchlist + replayed feed day → digest contains expected tender with score; org isolation holds.

## 7. Consumer C — GTM prospect DB (runs NOW, standalone)

- Prospect score (view over `company_activity`): CPV-family fit (71/72/79/80/85/90) × activity (≥3 awards/24m) × size proxy (avg award €30k–1.5M — SME band; exclude giants and micro) × recency. Weights in one config dict — tune after first outreach batch.
- Export: `python -m placsp_core.prospects --out prospects.csv` → columns: empresa, NIF, CPVs, awards_24m, importe_medio, órganos habituales, **evidencia** (2–3 expediente ids + URLs to cite in the personalized email / validation call prep).
- Feeds the outreach module (scraper→researcher→review→send) and `07-validation-call-script.md` pre-call prep.
- **Explicitly not promised**: loss-rate / win-rate (denominator not in the data — see §1).

## 8. Acceptance (layer-wide)

1. Backfill 3 months of ZIPs → row counts plausible vs feed stats; re-run → zero new rows (idempotent).
2. One expediente followed across states → single tender row, latest estado, award attached after adjudicación.
3. Multi-lot tender → one award per lot, amounts sum correctly.
4. Persona-física adjudicatario → flagged, absent from prospects export.
5. Prospect export produces ≥1 evidence expediente per company, URLs resolve.
6. Parser-version bump + re-parse path works on a sample.

## 9. Opus review checklist

- [ ] XPath map covers: expediente, órgano, título, CPV (multiple), importe, procedimiento, estado, plazo, doc links, adjudicatario NIF+nombre, importe adjudicación, num_ofertas, lotes — each with a fallback path or explicit None.
- [ ] Dedupe key is (expediente, órgano) — expediente alone collides across órganos.
- [ ] Upserts idempotent; `updated_at` monotonic guard (never overwrite newer with older).
- [ ] Persona-física exclusion enforced at export AND at scoring view level.
- [ ] URL import downloads only from the host allowlist; size/content-type limits enforced; no redirects followed off-allowlist.
- [ ] Radar scoring capped per org/day and metered (spec-2.2b §5); no unbounded LLM loops over the feed.
- [ ] `placsp_core` has zero imports from product code (standalone constraint).
- [ ] Attribution/reuse note present in README (Ley 37/2007; source: Plataforma de Contratación del Sector Público).

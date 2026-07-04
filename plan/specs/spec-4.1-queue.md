# Spec 4.1 — Queue-based processing pipeline

> Fable-written spec, 2026-07-02. Implementer: Opus 4.8. Review: checklist at end. Prereqs: 2.1 (Docker), 2.2 (Bicep), 2.4 (Alembic).
> ♻ Full rewrites: `services/pipeline.py` (→ worker), `services/ocr.py`, `services/memoria.py`, `endpoints/memoria.py`.

## 1. Problem being solved

FastAPI `BackgroundTasks` runs OCR→embed→index (and memoria generation) in-process: restart mid-job = pliego stuck in `processing` forever; no retry; long jobs hold DB connections (origin of the "fresh session" workaround in requirements.py — delete that pattern, it becomes unnecessary).

## 2. Architecture

- **Azure Storage Queues** (already have the storage account; Service Bus is overkill for per-client volume): `jobs` queue + `jobs-poison`.
- **Worker**: same backend image, different entrypoint (`python -m app.worker`). Separate Container App, KEDA queue scaler, min 0 / max 2 replicas. Shares `services/` code with the API.
- API enqueues; worker dequeues, executes, updates DB status.

## 3. Job contract

```json
{ "job_id": "<uuid>", "type": "process_pliego" | "generate_memoria" | "reindex_pliego",
  "payload": { "pliego_id": "..." } | { "licitacion_id": "...", "doc_id": "...", "user_id": "..." },
  "enqueued_at": "iso8601", "attempt": 1 }
```

- Visibility timeout: 10 min; worker renews (update_message) every 5 min while running — jobs may run 30+ min (large pliegos, memoria fan-out).
- Poison handling is **worker-side logic** (Storage Queues have no automatic poison routing): on dequeue, if `message.dequeue_count >= 3` → copy to `jobs-poison`, delete from `jobs`, mark resource `error` with `error_message="processing failed after 3 attempts"`.
- KEDA scaler auth: use managed identity if the ACA API version supports it for azure-queue rules; else a connection-string secret scoped to the scaler only (document which was used).
- **Idempotency required**: `process_pliego` re-run must first delete existing chunks for that pliego from the index (delete-then-index, function exists), then reprocess. `generate_memoria` re-run overwrites the draft doc. State transitions guard double-processing: worker only proceeds if status in (`uploaded`,`processing`,`error`).

## 4. Status model additions

- `pliegos.processing_started_at` (nullable datetime) — set by worker on dequeue. (Schema change — confirm with Jorge.)
- Stuck detection: API-side, on read: `status == processing AND processing_started_at < now-45min` → surface as `stalled` in responses (no DB write needed; derived).
- `POST /licitaciones/{id}/documents/{pliego_id}/reprocess` (org admin): allowed when status in (`error`, stalled-derived); re-enqueues.

## 5. Memoria generation on the worker

- `POST .../memoria/propuesta` becomes: create `MemoriaDocument` row with `status='generating'` (**new column — schema change, confirm with Jorge**; default `'ready'` backfills existing rows), enqueue `generate_memoria`, return 202 + doc_id.
- Frontend polls doc (existing GET) until `status='ready'` (or `error`). Chat-driven edits stay synchronous (they're short).
- Section fan-out parallelism stays inside the worker job (asyncio.gather as today’s design intends).

## 6. Worker skeleton requirements

- Async main loop, `receive_messages(max_messages=1)`, explicit delete on success.
- Per-job fresh DB session; no session crosses jobs.
- Structured logs with `job_id`, `pliego_id`/`licitacion_id`, attempt; App Insights events `job_started/succeeded/failed` (feeds 4.2 alerts).
- Graceful shutdown: SIGTERM → finish current job (Container Apps gives 30s+; set terminationGracePeriod 300s in Bicep) or abandon (message reappears after visibility timeout — safe due to idempotency).
- Local dev: Azurite queue or a `--once` CLI mode that processes one job inline; `docker-compose` gets a worker service.

## 7. What disappears

- `BackgroundTasks` usage in licitaciones/memoria endpoints.
- `run_ocr_and_index_pipeline` as an in-API call (becomes worker handler).
- `session_factory` fresh-session workaround in `services/requirements.py` (5.5 rewrite runs on worker or stays sync-short; either way the workaround pattern is banned).

## 8. Tests (acceptance)

1. Enqueue → worker processes → pliego `indexed` (integration, Azurite or mocked queue client).
2. Kill worker mid-job (simulate: raise between OCR and index) → message redelivered → completes on attempt 2 → no duplicate chunks (delete-then-index asserted).
3. 3 failures → poison queue + pliego `error` with message.
4. Stalled derivation: `processing_started_at` 1h ago → API reports stalled; reprocess endpoint re-enqueues.
5. Memoria: propuesta returns 202; doc transitions generating→ready; poll sees it.
6. Concurrent duplicate enqueue of same pliego → second job no-ops (status guard).

## 9. Opus review checklist

- [ ] No `BackgroundTasks` import remains for pipeline/memoria work.
- [ ] Visibility renewal implemented (long jobs won't double-run); renewal interval < visibility timeout / 2.
- [ ] Idempotency: delete-then-index before reprocess; status guards on dequeue.
- [ ] Poison path sets user-visible `error_message`; nothing stays `processing` forever in any failure branch (walk every except/return).
- [ ] Per-job DB session; none opened before dequeue or shared across jobs.
- [ ] 202 contract for memoria; frontend polling matches (or interim patch documented).
- [ ] Bicep updated: queue, worker app, KEDA scaler, grace period; deploy workflow builds one image, two apps.
- [ ] All 6 acceptance tests present.
- [ ] `pipeline.py`/`ocr.py`/`memoria.py` are rewrites per §2.2 rules of 00-CONTEXT (not the old files with a queue bolted on).

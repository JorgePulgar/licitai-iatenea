# Phase 4 — Reliability (what makes the maintenance contract honest)

> Prereq reading: `plan/00-CONTEXT.md` §2 (rewrite rules).
> **Status:** DM5 ✅ 2026-07-16 (4.1's ♻-scope only: `services/memoria.py` + `endpoints/memoria.py` rewritten, synchronous). Done tasks get ✅ on their heading here; canonical status lives in `00-CONTEXT.md` §5 (phase table) + §2 (inventory) + the DM table in `specs/spec-demo-minimal.md`. Note: **DM5 implements only 4.1's ♻-scope** (memoria service/endpoint rewrite, synchronous, NO queue/worker) — 4.1's queue work here remains open (pipeline.py/ocr.py rewrites included).

## 4.1 ♻ Queue-based processing pipeline — L — Opus 4.8 implement, Fable 5 spec + diff review

Current design: FastAPI `BackgroundTasks` runs OCR→embed→index in-process. Server restart mid-job = pliego stuck in `processing` forever; no retry; long jobs hold DB connections (the "fresh session" workaround in requirements.py exists because of this).

- Azure Storage Queue + worker container (Container Apps, scale-to-zero, KEDA queue scaler). API enqueues `{pliego_id}`; worker runs the pipeline.
- Retry with poison-queue after N attempts; pliego marked `error` with message.
- Stuck-job recovery: `processing` older than 30 min → flagged, requeue-able endpoint.
- Memoria generation (multi-agent fan-out) moves to the worker too — it's the longest-running job.
- ♻ scope — full rewrites: `services/pipeline.py` (becomes worker entrypoint), `services/ocr.py`, `services/memoria.py`, `endpoints/memoria.py`.
- Bicep update: queue + worker app (amend 2.2 templates).

**Acceptance:** kill the worker mid-job → job retried and completes; no pliego ever stuck in `processing`; poison case surfaces as `error` with a message.

## 4.2 Alerts — M — Sonnet 5

App Insights: error-rate alert, P95 latency alert, pipeline-failure alert (custom event), availability ping on `/health`. Action group → Jorge's email. In Bicep. **Acceptance:** synthetic failure triggers the email.

## 4.3 Deep health endpoint — S — Haiku 4.5

`GET /health/deep`: per-dependency status (SQL, Search, Storage, OpenAI) with timeouts, admin-only or private. **Acceptance:** degraded dependency reported without crashing the endpoint.

## 4.4 Runbooks — S — Sonnet 5

`docs/runbooks/`: restore SQL (PITR), rebuild Search index from blobs, rotate secrets, onboard new client (Bicep→CLI→invite), incident triage (where to look in App Insights). **Acceptance:** each executable start-to-finish by future-you at 2 AM.

## 4.5 GDPR sales pack + legal check — S — Fable 5 drafts → lawyer

- DPA template, subprocessor list (Microsoft), data-flow diagram, retention policy (`RETENTION_DAYS` per env), right-to-erasure statement (endpoint exists).
- Same lawyer consult sanity-checks the §2 rewrite completion (bring the inventory + a couple of before/after file pairs).

**Acceptance:** pack attachable to client contracts; written lawyer opinion on the rewrite approach.

---

Done when: a client env survives restarts and bad inputs without manual intervention, and problems reach Jorge's inbox before the client notices.

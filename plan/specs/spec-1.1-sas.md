# Spec 1.1 — Upload/download security redesign (SAS + blob_url trust)

> Fable-written spec, 2026-07-02. Implementer: Opus 4.8. Review: against THIS spec, checklist at the end.
> ♻ Full rewrite of `services/ingestion.py` and the SAS/upload paths of `endpoints/licitaciones.py`. Do not port the old code.

## 1. Current state and vulnerabilities

1. **`GET /licitaciones/upload-token`** (`endpoints/licitaciones.py:28`) issues a **container-level** SAS (write+create, 1h) to the browser. Any authenticated user can create or overwrite ANY blob in `pliegos-raw`, including other users' pliegos and `company-templates/{other_user}/...`.
2. **Client-controlled `blob_url`**: after direct upload, the client sends `blob_url` strings in the create-licitación request; the pipeline later calls `download_pliego_bytes(blob_url)` (`services/ingestion.py:29`), which accepts **any URL — including `file://` paths** (local file read on the server) or another user's blob URL (cross-user read via OCR output). Nothing validates that the URL points at the expected account/container/path.
3. Positive pattern to keep: `GET .../documents/{pliego_id}/view-url` already issues per-blob read-only 1h SAS with an ownership check.

## 2. Design decisions

**D1 — Per-blob SAS, server-named blobs.** Azure SAS cannot scope to a path prefix on flat-namespace storage (container-level or blob-level only), so per-blob is the only correct granularity. The **server generates the full blob path**; the client never chooses a path.

**D2 — Upload registration (kills the blob_url trust problem).** The backend records every issued upload; the create-licitación request references `upload_id`s, never raw URLs. `blob_url` disappears from all request schemas (stays in responses/DB).

**D3 — SAS type**: account-key SAS now; switch the same helper to **user-delegation SAS** when task 1.4 lands Managed Identity (parameterize credential acquisition in one function so 1.4 changes one place). Never regex the account key out of the connection string (current code does) — use `BlobServiceClient.credential`.

## 3. Contracts

### 3.1 `POST /api/v1/licitaciones/upload-urls`  (auth required; replaces `GET /upload-token`)

Request:
```json
{ "files": [ { "filename": "pcap.pdf", "size_bytes": 1048576, "content_type": "application/pdf" } ] }
```
Rules: 1–10 files; `size_bytes` ≤ 100 MB each; `content_type` must be `application/pdf`; filename sanitized (`[^a-zA-Z0-9._-]` → `_`, max 200 chars).

Response (per file):
```json
{ "uploads": [ { "upload_id": "<uuid>", "upload_url": "https://<acct>.blob.core.windows.net/pliegos-raw/uploads/<user_id>/<upload_id>/pcap.pdf?<sas>", "expires_at": "..." } ] }
```

- Blob path: `uploads/{user_id}/{upload_id}/{safe_filename}` — collision-free by construction, user-attributed for cleanup/audit.
- SAS permissions: **create + write**, that single blob only, **TTL 15 min**. No read, no delete, no list.
- Server persists an `Upload` row: `id`, `user_id`, `blob_path`, `filename`, `declared_size`, `content_type`, `created_at`, `consumed_at (nullable)`. (New table — small, but it IS a schema change: confirm with Jorge before migrating.)

### 3.2 Create licitación (modified)

`documents[]` items change `blob_url` → `upload_id`. Backend, per upload_id:
1. Row exists, `user_id` matches caller, `consumed_at` is NULL → else 400.
2. Blob actually exists at the recorded path (HEAD) and size ≤ limit → else 400.
3. `validate_pdf_bytes` on download during pipeline (existing behavior).
4. Mark `consumed_at`; store the **server-recorded** path in `Pliego.blob_path` / canonical URL in `blob_url`.

### 3.3 Download path hardening (`services/ingestion.py` rewrite)

- `download_pliego_bytes(blob_path)` takes a **container-relative path**, not a URL. Drop `file://` support entirely (tests use mocks; local-dev fallback if truly needed = explicit `settings.LOCAL_STORAGE_DIR` + path traversal guard, NOT scheme sniffing).
- `delete_pliego_blob` same treatment.
- Callers (`pipeline.py`, `ocr.py`, auth delete, retention) pass `pliego.blob_path`.

### 3.4 `view-url` endpoint

Keep design; move SAS generation into the shared helper; check licitación ownership **before** querying the pliego; TTL stays 1h (PDF viewing sessions are long).

### 3.5 Orphan cleanup

Retention job addition: delete `uploads/` blobs older than 24h whose `Upload.consumed_at` is NULL (abandoned uploads).

## 4. Frontend interim patch (until Phase FE)

`blobStorage.ts`: request `upload-urls`, PUT each file to its `upload_url` (BlockBlobClient accepts a full SAS URL), send `upload_id`s in the create request. Delete the container-client code path.

## 5. Tests (acceptance)

1. Isolation: user A's SAS URL cannot PUT to a path outside `uploads/{A}/...` (SDK rejects — assert 403 from storage on a crafted path swap).
2. `upload_id` of user A submitted by user B → 400, licitación not created.
3. Reused (consumed) upload_id → 400.
4. `file://` and cross-container paths in any persisted field → impossible by construction; unit test that `download_pliego_bytes` rejects absolute URLs/paths outside the container.
5. Declared vs actual: blob missing at create time → 400 with clear message.
6. Happy path e2e: request URLs → PUT → create → pipeline processes.

## 6. Opus review checklist (review the diff against this, not the old code)

- [ ] No container-level SAS anywhere (`generate_container_sas` gone from the codebase).
- [ ] No regex extraction of AccountKey; credential comes from client object / injected helper.
- [ ] Blob path built ONLY server-side; no client string ever concatenated into a path.
- [ ] SAS TTL ≤ 15 min for uploads; create+write only.
- [ ] `blob_url` absent from all request schemas; `upload_id` flow enforced with the 4 checks in §3.2.
- [ ] `file://` handling deleted; no URL-scheme branching remains in ingestion.
- [ ] `Upload` table migration reviewed; `consumed_at` set atomically with licitación creation (same transaction).
- [ ] All 6 acceptance tests present and passing; isolation test actually asserts storage-level rejection.
- [ ] Old endpoints removed (`/upload-token` 404s); frontend patched to match.

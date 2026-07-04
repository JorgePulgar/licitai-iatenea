# Spec 3.3 / 3.4 — Invite & password-reset token semantics

> Fable-written spec, 2026-07-02. Implementer: Opus 4.8. This is auth code — implement exactly as written; deviations need a written reason.
> Prereqs: 3.1 (org), 3.2a (email service).

## 1. Shared token design (one mechanism, two purposes)

Table `auth_tokens`: `id` (pk), `user_id` (nullable — invite may precede user row: see §2), `org_id`, `email` (lowercased), `purpose` ('invite'|'password_reset'), `token_hash` (sha256 of the secret; **plaintext never stored**), `expires_at`, `used_at` (nullable), `created_by`, `created_at`.

- Secret: `secrets.token_urlsafe(32)`, sent only inside the email link: `https://<app>/auth/<purpose>?token=<secret>`.
- Validation: hash lookup + `used_at IS NULL` + `expires_at > now`. On success set `used_at` **in the same transaction** as the password write (single-use is transactional, not best-effort).
- Expiry: invite 72h, reset 1h.
- Issuing a new token for the same email+purpose voids previous unused ones (`used_at = now`, reason logged).
- Never log the secret; log token `id` only.

## 2. Invite flow (3.3)

1. `POST /api/v1/org/invites` (admin only): `{email, role}`. If email already belongs to an active user in ANY org → **200 with generic body anyway** (no cross-org enumeration), no email sent... EXCEPT same-org active user → 409 (admin may know their own org). User row strategy: create `users` row up-front with `is_active=false`, `password_hash=''` placeholder is REJECTED — instead create no user row; invite stores email+org+role; user row is created at acceptance. (Avoids half-users in queries.)
2. Email via ACS template with link.
3. `GET /api/v1/auth/invites/{token}` → `{email, org_name, valid: true}` for the form (invalid/expired → 404, generic).
4. `POST /api/v1/auth/invites/{token}/accept`: `{password}` (policy: ≥10 chars, not equal to email local-part; bcrypt as existing). Validate the invite's org still exists and `is_active` → else 404 generic. Transaction: create user (active, role from invite, org from invite) + mark token used → auto-login response (JWT) or 201 + redirect to login (implementer picks; document).
5. Rate limit: 10 invites/hour/admin (slowapi, from 1.2).

## 3. Password reset (3.4)

1. `POST /api/v1/auth/password-reset`: `{email}` → **always 202 with identical body and near-constant timing** (do the DB lookup + email send async/fire-and-forget so response timing doesn't leak existence). 5/min/IP rate limit.
2. Email only if user exists + active.
3. `POST /api/v1/auth/password-reset/{token}`: `{new_password}` → validate token, set password, mark used, **invalidate other outstanding reset tokens for the user**, and bump a `users.token_version` int included in JWT claims so existing JWTs are revoked on password change (`get_current_user` compares claim vs row; mismatch → 401). `token_version` is a schema addition — confirm with Jorge.
4. Confirmation email after successful reset ("if this wasn't you…").

## 4. Tests (acceptance)

1. Invite: admin invites → email captured (mock ACS) → accept sets password, user active in right org+role; token unusable twice (parallel double-accept: exactly one succeeds — DB-level test with two sessions).
2. Expired/used/garbage token → 404 generic on GET and POST.
3. Member calling invite endpoint → 403.
4. Reset: unknown email → 202 identical body; known email → email sent; token single-use; old JWTs 401 after reset (token_version).
5. New invite voids old invite token.
6. No secret or password appears in any log line (assert via caplog).

## 5. Opus review checklist

- [ ] Token stored ONLY as sha256 hash; secret only in the emailed URL.
- [ ] Single-use enforced in the same DB transaction as the credential write; double-accept race test present.
- [ ] Enumeration: reset always 202; invite responses per §2.1 exactly; timings decoupled (send async).
- [ ] `token_version` JWT revocation wired into `get_current_user`.
- [ ] Rate limits from 1.2 applied to both endpoints.
- [ ] Password policy enforced server-side; bcrypt via existing `hash_password`.
- [ ] No user row created before invite acceptance.
- [ ] All 6 test groups present and passing.

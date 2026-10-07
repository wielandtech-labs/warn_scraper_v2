# Auth operations

The API has cookie-session auth with four roles:

| Role  | Sees                                                                  |
|-------|-----------------------------------------------------------------------|
| free  | Same as anonymous (the public site shape) — login adds nothing yet    |
| paid  | + provider fields on companies: parent_company_name, global_ultimate_name, hq_address, employee_count |
| enterprise | Same as paid, plus the raw unique ids: unique_id, parent_unique_id |
| admin | Same as enterprise, plus `/admin/companies` (merge/unmerge company records; `require_admin`) |

Accounts are admin-provisioned (self-signup exists but ships dark behind
`SIGNUP_ENABLED`). User management is via the CLI (`invite-user`,
`create-user`, `set-role`, `list-users`, `delete-user`), run inside the
cluster so it can reach the database.

Sessions: 30-day absolute expiry, httpOnly+Secure+SameSite=Lax cookie
(`warn_session`); the DB stores only a sha256 of the token. Expired rows are
pruned opportunistically at each login. `AUTH_COOKIE_SECURE=0` disables the
Secure flag for plain-HTTP local dev only.

## Inviting a user in production

`invite-user` creates the account and emails a single-use link where the
invitee sets their own password — no password ever passes through you, a
manifest, or an inbox. Run it in the api pod, which already has the DB and
SMTP env:

```bash
kubectl -n warn-v2 exec deploy/warn-v2-warn-v2-api -- \
  uv run warn-v2 invite-user --email someone@example.com --role admin
```

- The link (`/api/auth/reset-page?token=…&invite=1`) is valid for **7 days**
  and works once. Using it sets the password and marks the email verified.
- Until then the account has an unusable random password, so nobody can log in.
- Re-running for an existing email sends a fresh link (and applies `--role`)
  instead of failing — use it when an invite expired or a previous attempt was
  left half-done. The existing password keeps working until the link is used.
- The link is never printed. If SMTP isn't configured the command exits 1
  and creates nothing.

`set-role` / `delete-user` / `list-users` run the same way via `kubectl exec`.

## Creating a user with a known password (no email)

`create-user` sets the password directly (interactive prompt or
`--password-stdin`) and marks the account verified. Prefer `invite-user`; use
this only when email isn't an option, and never put the password in a
manifest or shell history — pipe it from a short-lived Secret:

```bash
kubectl -n warn-v2 create secret generic warn-v2-user-bootstrap \
  --from-literal=password='<the-password>'
# then a one-off Job running:
#   printf '%s' "$BOOTSTRAP_PASSWORD" | uv run warn-v2 create-user \
#     --email "$BOOTSTRAP_EMAIL" --role admin --password-stdin
# with BOOTSTRAP_PASSWORD from that secret and DATABASE_URL from warn-v2-db;
# delete both the Job and the secret afterwards.
```

## Data-exposure note

provider-sourced fields were deliberately excluded from the public API
(see the comment in `warn_v2/api/schemas.py`); serving them to paid logins is
a deliberate owner decision (2026-06-11) and is limited to authenticated
paid/admin sessions.

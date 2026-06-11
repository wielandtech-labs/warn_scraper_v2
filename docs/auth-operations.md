# Auth operations

The API has cookie-session auth with three roles:

| Role  | Sees                                                                  |
|-------|-----------------------------------------------------------------------|
| free  | Same as anonymous (the public site shape) — login adds nothing yet    |
| paid  | + D&B fields on companies: duns, parent_duns, parent_company_name, global_ultimate_name, hq_address, employee_count |
| admin | Same as paid; reserved for future admin endpoints (`require_admin`)   |

Accounts are **admin-provisioned only** — there is no signup endpoint. User
management is via the CLI (`create-user`, `set-role`, `list-users`,
`delete-user`), run inside the cluster so it can reach the database.

Sessions: 30-day absolute expiry, httpOnly+Secure+SameSite=Lax cookie
(`warn_session`); the DB stores only a sha256 of the token. Expired rows are
pruned opportunistically at each login. `AUTH_COOKIE_SECURE=0` disables the
Secure flag for plain-HTTP local dev only.

## Creating a user in production (one-off Job)

Never put the password in the manifest or shell history of the pod spec —
stage it in a short-lived Secret and pipe it via `--password-stdin`:

```bash
# 1. ad-hoc secret with the password (generate one, e.g. openssl rand -base64 24)
kubectl -n warn-v2 create secret generic warn-v2-user-bootstrap \
  --from-literal=password='<the-password>'

# 2. one-off Job (set the image to the currently deployed tag)
kubectl -n warn-v2 apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata:
  name: warn-v2-create-user
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: create-user
          image: ghcr.io/wielandtech-labs/warn-v2:<CURRENT_TAG>
          command: ["sh", "-c"]
          args:
            - printf '%s' "$BOOTSTRAP_PASSWORD" |
              uv run warn-v2 create-user
              --email "$BOOTSTRAP_EMAIL" --role admin --password-stdin
          env:
            - name: BOOTSTRAP_EMAIL
              value: you@example.com
            - name: BOOTSTRAP_PASSWORD
              valueFrom:
                secretKeyRef: { name: warn-v2-user-bootstrap, key: password }
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef: { name: warn-v2-db, key: url }
EOF

# 3. verify, then clean up BOTH the Job and the secret
kubectl -n warn-v2 logs job/warn-v2-create-user
kubectl -n warn-v2 delete job warn-v2-create-user secret/warn-v2-user-bootstrap
```

`set-role` / `delete-user` / `list-users` work the same way (no password
needed — drop the secret and the stdin pipe).

## Data-exposure note

D&B-sourced fields were deliberately excluded from the public API
(see the comment in `warn_v2/api/schemas.py`); serving them to paid logins is
a deliberate owner decision (2026-06-11) and is limited to authenticated
paid/admin sessions.

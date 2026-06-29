---
description: Regenerate STATE_AUDIT.md from a trusted in-cluster prod audit run, then open a PR
argument-hint: "(no args)"
---

# Refresh the state data-quality audit

You are regenerating the **generated** per-state table in `STATE_AUDIT.md` from a
trusted run of `warn-v2 audit --markdown` **in-cluster**, so the prod `DATABASE_URL`
is read via `secretKeyRef` and no credentials leave the cluster. Then you open a PR
for human review.

**This is done only when ALL of these hold** — treat as the success criterion and
loop until actually met, not until it "looks right":

1. The audit ran against the **live deployed prod image** (not a local DB, not an
   ad-hoc `kubectl cp`/`exec`), the Job reached `complete`, and its log is a
   well-formed markdown table (12 columns, ~45+ state rows).
2. `STATE_AUDIT.md`'s generated block (between the markers) holds the fresh table +
   a fresh `_Generated …_` note line, and the diff touches **only** that block plus
   any minimal, factual annotation reconciliation.
3. A PR is open with the change. **Never merge** — merging `main` is a production
   deploy (the image-tag chain in `CLAUDE.md` runs unattended).

## Setup (run once at the start)

```bash
# kubectl/flux live in WSL (project CLAUDE.md) — every kubectl call is `wsl kubectl`.
# gh needs a token (global CLAUDE.md — stale keyring auth on this host):
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | git credential fill | sed -n 's/^password=//p')
```

## Step 1 — Run the audit in-cluster, capture the table

Use the **live deployed** image tag (this also confirms the `audit` command is in
the running image):

```bash
TAG=$(wsl kubectl -n warn-v2 get deploy warn-v2-warn-v2-api \
        -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "$TAG"   # e.g. ghcr.io/wielandtech-labs/warn-v2:20260629-134906-3c8fcb3
```

Run a one-off Job (clean stdout), wait, capture to a scratch file, clean up:

```bash
wsl kubectl -n warn-v2 apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: warn-v2-audit
  namespace: warn-v2
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: audit
          image: ${TAG}
          args: ["audit","--markdown"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: warn-v2-db
                  key: url
EOF

wsl kubectl -n warn-v2 wait --for=condition=complete job/warn-v2-audit --timeout=180s
wsl kubectl -n warn-v2 logs job/warn-v2-audit > /tmp/audit-table.md
wsl kubectl -n warn-v2 delete job warn-v2-audit
```

**The `uv run` entrypoint prints 3–4 build/install lines before the table** ("Building
warn-v2 …", "Installed 1 package …"). Keep only from the `| State | Active | …` header
onward — discard everything before it. The note line (`_Generated …_`) is **not** in
the output; you compose it in Step 2.

Failure handling:
- Job fails with **"No such command 'audit'"** → the deployed image predates the
  audit command. Stop and report; do **not** fabricate a table.
- `wait` times out / Job `failed` → `wsl kubectl -n warn-v2 logs job/warn-v2-audit`
  for the error (commonly a DB-connect issue). Fix or report; don't proceed.

## Step 2 — Splice into `STATE_AUDIT.md`

The generated block lives between `<!-- BEGIN GENERATED TABLE -->` and
`<!-- END GENERATED TABLE -->`. Replace **only** its contents with:

1. A fresh note line (use today's date and the `$TAG` you ran):
   ```
   _Generated <YYYY-MM-DD> from prod via `warn-v2 audit --markdown`
   (image `<tag>`)._
   ```
2. The captured table body (header + separator + all state rows), verbatim.

Drop any one-off "⚠ stale rows" warning left in the old block — a fresh regeneration
supersedes it.

Then **lightly reconcile** the hand-curated prose with what the new data shows —
factual, dated, minimal:
- If states moved to `fetch_failed` / `broken`, add a dated "scraper health at this
  run" line to **Source notes**, and qualify any older "now ok" claim it contradicts.
  (`fetch_failed` is often a transient source block, not a parser break — point to
  `/heal-scraper` to classify rather than asserting a regression.)
- Note material backfills (big Active jumps, new year ranges, newly-live states) and
  any geo% drops they caused.

Do **NOT** rewrite the Rubric, Legend, or the dated "Geocoding root cause"
investigation log. No chart version bump — this is docs-only (see `CLAUDE.md`).

## Step 3 — Open a PR (never merge)

```bash
# Don't open a duplicate:
gh pr list --state open --search "STATE_AUDIT" --json number,title
```

If an open audit-refresh PR already exists, stop and report it. Otherwise:

- Branch: `docs/state-audit-<yyyymmdd>`
- Commit: `docs: refresh STATE_AUDIT.md from prod audit (<yyyy-mm-dd>)`
- PR body: the image tag the audit ran against, a one-line summary of the notable
  deltas (new/broken scrapers, big backfills, geo movement), and a note that this is
  docs-only (no chart bump). Run `/code-review` before the human merges.

## Step 4 — Summarize

One short roll-up: the image tag, row count, any `broken`/`fetch_failed` states, the
biggest deltas vs the previous table, and the PR number.

---

## Running this as a scheduled task

Unlike `/heal-scraper` (local-only), this routine **needs WSL `kubectl` cluster
access** and `gh` auth. Validate `claude -p "/refresh-audit"` once interactively —
confirm WSL `kubectl` reaches the cluster and the `GH_TOKEN` shim resolves
non-interactively — before trusting a scheduled run.

**Auto mode (no prompts).** In headless `-p` mode there's no one to answer a
permission prompt, and the **first un-allowlisted tool call aborts the whole run**
with a non-zero exit (it doesn't hang or skip). `--permission-mode acceptEdits`
auto-approves file edits but **not** the `wsl kubectl` / `git` / `gh` Bash this
routine runs — so it would abort at the first `git` step, *after* touching the
cluster. For a trusted, bounded task (read-only audit + a PR it never merges), run
with **`--dangerously-skip-permissions`** (≡ `--permission-mode bypassPermissions`),
which skips all prompts. This also avoids allowlisting the `GH_TOKEN` shim (a
`git credential fill` pipeline that's awkward to express as an allow rule). Don't
hand this flag to anything that *merges* — the success criteria above (never merge)
are what keep auto mode safe.

The audit is a slow-moving snapshot, so **weekly** is plenty. Windows Task Scheduler
example (Mondays 09:00, after the nightly scrape/enrich window):

```powershell
$claude = (Get-Command claude).Source
$action = New-ScheduledTaskAction -Execute $claude `
  -Argument '-p "/refresh-audit" --dangerously-skip-permissions' `
  -WorkingDirectory 'C:\Users\rapha\workspace\warn_scraper_v2'
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9:00am
Register-ScheduledTask -TaskName 'warn-refresh-audit' -Action $action -Trigger $trigger
```

`-WorkingDirectory` sets the cwd (the proven mechanism — there's no need for a
`claude` cwd flag). Output is a draft PR for human review — nothing deploys until
you merge.

- **Run once, interactively:** `/refresh-audit`
- **Re-check on an interval:** `/loop 7d /refresh-audit`

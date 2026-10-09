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
   well-formed markdown table (13 columns, ~45+ state rows).
2. `STATE_AUDIT.md`'s generated block (between the markers) holds the fresh table +
   a fresh `_Generated …_` note line, and the diff touches **only** that block plus
   any minimal, factual annotation reconciliation.
3. A PR is open with the change, and it is merged **only** behind the Step 3 guards.
   Merging `main` is normally a production deploy, but a `STATE_AUDIT.md`-only diff
   is not: `docker.yml`'s `paths` filter skips `**.md` (re-including only
   `warn_v2/reports/published/**`), so no image is built and the
   image-tag chain in `CLAUDE.md` never fires. Any diff reaching beyond
   `STATE_AUDIT.md` is **not** merged by this routine.

## Setup (run once at the start)

```bash
# kubectl/flux live in WSL (project CLAUDE.md) — every kubectl call is `wsl kubectl`.
# gh auth: GH_TOKEN is preset in Bash by a SessionStart hook (global CLAUDE.md).
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
- Never name the commercial enrichment vendor — this repo is public. Call that
  tier "provider" (as in `enrichment_source == "provider"`), even if an older
  block of this file or a prior audit used the vendor's name.

Do **NOT** rewrite the Rubric, Legend, or the dated "Geocoding root cause"
investigation log. No chart version bump — this is docs-only (see `CLAUDE.md`).

## Step 3 — Open a PR, then merge it when the guards pass

```bash
# Don't open a duplicate. NOTE: `--search` silently returns [] on org repos with
# this host's token (no read:org) — that is what let a duplicate PR be opened on
# 2026-07-27. Use a plain list and filter client-side.
gh pr list --state open --json number,title,headRefName | grep -i 'state-audit'
```

An already-open audit PR means a previous run's merge didn't land. Put it through
the guards below — merge it if it passes, otherwise report it and stop — then
continue with today's refresh.

Otherwise:

- Branch: `docs/state-audit-<yyyymmdd>`
- Commit: `docs: refresh STATE_AUDIT.md from prod audit (<yyyy-mm-dd>)`
- PR body: the image tag the audit ran against, a one-line summary of the notable
  deltas (new/broken scrapers, big backfills, geo movement), and a note that this is
  docs-only (no chart bump).

### Merging is allowed here, behind three checked guards

`main` has no branch protection and the repo has `allow_auto_merge: false`, so
GitHub-native auto-merge is unavailable and would be meaningless anyway (nothing is
required, so `--auto` merges instantly). The gate goes in the routine, per global
CLAUDE.md: poll the check run, then merge. `ci.yml` has no paths filter, so `test`
and `frontend` do run on a docs PR and are a real signal.

Use **REST** to merge. `gh pr merge` is GraphQL-backed and hits the `read:org`
token gap mid-run.

```bash
REPO=wielandtech-labs/warn_scraper_v2
PR=<n>
SHA=$(gh api repos/$REPO/pulls/$PR --jq .head.sha)

# Guard 1 — the diff touches exactly one file, and it is STATE_AUDIT.md.
gh api repos/$REPO/pulls/$PR/files --jq '.[].filename'

# Guard 2 — every check run on that SHA is completed/success.
#           (`mergeable` means no merge conflict, NOT CI-green.)
gh api repos/$REPO/commits/$SHA/check-runs \
  --jq '.check_runs[] | "\(.name): \(.status)/\(.conclusion)"'

# Guard 3 — nothing was pushed since: `sha` makes the merge 409 if the head moved.
gh api -X PUT repos/$REPO/pulls/$PR/merge -f merge_method=squash -f sha="$SHA"
gh api -X DELETE repos/$REPO/git/refs/heads/docs/state-audit-<yyyymmdd>
```

If the file list holds anything but `STATE_AUDIT.md`, or any check is not
`completed/success`, or the head SHA moved — **do not merge.** Leave the PR open and
report it. A diff beyond `STATE_AUDIT.md` can build an image, which is the case the
old blanket "never merge" rule existed for.

## Step 4 — Summarize

One short roll-up: the image tag, row count, any `broken`/`fetch_failed` states, the
biggest deltas vs the previous table, and the PR number.

---

## Running this as a scheduled task

Unlike `/heal-scraper` (local-only), this routine **needs WSL `kubectl` cluster
access** and `gh` auth. Validate `claude -p "/refresh-audit"` once interactively —
confirm WSL `kubectl` reaches the cluster and `gh` auth (`GH_TOKEN` from the
SessionStart hook) resolves non-interactively — before trusting a scheduled run.

**Auto mode (no prompts).** In headless `-p` mode there's no one to answer a
permission prompt, and the **first un-allowlisted tool call aborts the whole run**
with a non-zero exit (it doesn't hang or skip). `--permission-mode acceptEdits`
auto-approves file edits but **not** the `wsl kubectl` / `git` / `gh` Bash this
routine runs — so it would abort at the first `git` step, *after* touching the
cluster. For a trusted, bounded task, run with **`--dangerously-skip-permissions`**
(≡ `--permission-mode bypassPermissions`), which skips all prompts.

This routine *does* merge, which is normally exactly what you must not hand this
flag to. It is safe here only because the merge is gated on a machine-checked
predicate — single-file `STATE_AUDIT.md` diff, all checks green, head SHA unmoved —
and because a `**.md`-only merge cannot build an image or reach the Flux chain.
Widen that diff and the flag stops being safe.

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
`claude` cwd flag). Output is a merged docs commit when the guards pass, or an open
PR plus a report when they don't. Either way nothing deploys — docs-only merges
build no image.

- **Run once, interactively:** `/refresh-audit`
- **Re-check on an interval:** `/loop 7d /refresh-audit`

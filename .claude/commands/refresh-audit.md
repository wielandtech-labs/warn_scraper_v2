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

## Setup

This routine needs only **read** access to the cluster (`get`/`watch` and pod logs,
e.g. the read-only `tailnet-readers` context) and `gh` auth for the PR. Put the
`kubectl` verb first (`kubectl get -n warn-v2 ...`): headless runs allowlist commands
by prefix.

## Step 1 — Read this week's in-cluster audit, capture the table

The audit runs as the chart's `warn-v2-warn-v2-audit` CronJob (`audit.enabled` in the
prod HelmRelease, Mon 06:30 America/Detroit). This step only **reads** it. Never
create, edit or delete a Job here.

1. **The release must be healthy.** Run both checks:

   ```bash
   kubectl get -n warn-v2 helmreleases.helm.toolkit.fluxcd.io warn-v2 \
     -o jsonpath='{.status.conditions[?(@.type=="Ready")].status} {.status.conditions[?(@.type=="Ready")].message}'
   kubectl get -n warn-v2 deploy warn-v2-warn-v2-api \
     -o jsonpath='{.status.readyReplicas}/{.spec.replicas} {.spec.template.spec.containers[0].image}'
   ```
   If the HelmRelease isn't `True`, or it's mid-rollback, or the API isn't fully
   ready, report that and stop.

2. **Find this week's Job.** It must be the newest audit Job from this release and
   created in the last 6 hours:

   ```bash
   kubectl get -n warn-v2 jobs -l app.kubernetes.io/instance=warn-v2,app.kubernetes.io/component=audit -o json \
     | jq -r --arg cut "$(date -u -d '6 hours ago' +%FT%TZ)" '
         [.items[] | select(.metadata.creationTimestamp >= $cut)]
         | sort_by(.metadata.creationTimestamp) | last
         | if . == null then "NONE"
           else "\(.metadata.name) succeeded=\(.status.succeeded // 0) active=\(.status.active // 0) failed=\(.status.failed // 0) image=\(.spec.template.spec.containers[0].image)" end'
   ```
   - `NONE`: this week's run is missing. Report it and stop. **The 6-hour cut is
     what keeps last week's Job out.** When this week's run fails, last week's
     successful Job can still exist, so never widen the cut or fall back to an
     older Job.
   - `active=1`: it's still running (the Job may start up to 10 minutes late and
     has a 10-minute deadline). Re-run the query once a minute, for up to 20
     minutes.
   - `failed=1`: report the failure with `kubectl logs -n warn-v2 job/<name>` and
     stop. Never fabricate a table.
   - `succeeded=1`: continue. **`TAG` is the Job's own `image=` tag**, used in Step 2.
     If it differs from the API deployment's image in check 1, a rollout landed
     after the audit. Say so in the PR body, but the table still belongs to `TAG`.

3. **Read the table:** `kubectl logs -n warn-v2 job/<name>`.

**Keep only from the `| State | Active | …` header onward** and discard anything before it.
Images built before the fix for #475 (PR #476) printed 3–4 build/install lines first ("Building warn-v2 …",
"Installed 1 package …"); since then the image sets `UV_NO_SYNC=1` and `uv run` prints none. The note line (`_Generated …_`) is **not** in
the output; you compose it in Step 2.

A log with **"No such command 'audit'"** means the image predates the audit command.
A failed Job is commonly a DB-connect issue, and its log says which. Either way,
report and stop.

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

On the homelab admin workstation this runs headless every Monday at 07:00
(`claude -p` from a systemd timer), 30 minutes after the CronJob. It runs with a
per-task tool allowlist and never skips permissions. It reaches the cluster only
through the read-only context, so the only write it can make anywhere is the guarded
`STATE_AUDIT.md` PR and its merge.

- **Run once, interactively:** `/refresh-audit`

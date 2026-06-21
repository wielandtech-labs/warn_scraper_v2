---
description: Reproduce and fix a broken WARN state scraper, then open a PR
argument-hint: "[STATE...]  (e.g. CA, or CA TX NY; empty = check every state)"
---

# Repair broken WARN state scrapers

You are repairing WARN state scrapers that have broken because the upstream page
or file format changed. This op replaces the retired in-app self-heal agent: you
*are* the agent, with real tools and a human reviewing the PR.

**A state is "fixed" only when ALL of these hold** — treat this as the success
criterion and loop until it's actually met, not until the change "looks right":

1. The live source reproduces cleanly: `validate()` returns `ok=True` (row count
   within `expected_row_range`, all `required_fields` present in >90% of rows).
2. The state's golden-fixture test still passes (don't fix live by breaking the
   committed sample).
3. The full test suite is green.

Keep diffs **surgical** — touch only the broken parser. Match the surrounding
style. **Never merge** a PR: merging `main` is a production deploy.

## Setup (run once at the start)

```bash
# Work from the repo/worktree root. The scraper deps live in the sibling venv
# (project CLAUDE.md): use its python with the worktree as cwd so the worktree's
# warn_v2 shadows the venv's editable install.
PY="C:/Users/rapha/workspace/warn_scrapper_v2/.venv/Scripts/python.exe"
# gh needs a token (global CLAUDE.md — stale keyring auth on this host):
export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | git credential fill | sed -n 's/^password=//p')
```

## Targets

`$ARGUMENTS` — a list of state abbreviations to repair. If empty, check **every**
registered state:

```bash
"$PY" -c "from warn_v2.scrapers.registry import all_states; print(' '.join(all_states()))"
```

## Per state `XX` (module `warn_v2/scrapers/states/<xx>.py`, fixtures `warn_v2/scrapers/fixtures/<xx>/`)

### 1. Reproduce the break live (no DB, no cluster)

```bash
"$PY" - <<'PY'
import sys, traceback
from warn_v2.scrapers.registry import get_scraper
from warn_v2.pipeline.validate import validate
state = "XX"
s = get_scraper(state)
try:
    raw = s.fetch()
except Exception as e:
    print(f"FETCH_FAILED: {type(e).__name__}: {e}")   # transient/network — not a code bug
    sys.exit(0)
try:
    rows = s.parse(raw)
except Exception:
    # persist the failing bytes for replay while you iterate on parse()
    from warn_v2.pipeline.runner import _save_snapshot
    p = _save_snapshot(state, raw)
    print(f"PARSE_RAISED, snapshot={p}\n{traceback.format_exc()}")
    sys.exit(0)
r = validate(s, rows)
print(f"VALIDATE ok={r.ok} rows={r.row_count} expected={s.expected_row_range} reason={r.reason}")
if not r.ok:
    from warn_v2.pipeline.runner import _save_snapshot
    print("snapshot=", _save_snapshot(state, raw))
PY
```

**Classify the result:**
- `FETCH_FAILED` → the source is down or blocking; this is **not** a parser bug.
  Report it as transient/skipped and move on. (If many states FETCH_FAIL at once,
  suspect the network, not the scrapers.)
- `PARSE_RAISED` or `VALIDATE ok=False` → a **real break**. The snapshot path is
  printed; you'll replay against it. Continue.
- `VALIDATE ok=True` → nothing to fix. Report "ok" and move on.

### 2. Diagnose

Read `warn_v2/scrapers/states/<xx>.py` and the golden fixture under
`warn_v2/scrapers/fixtures/<xx>/`. Inspect the saved snapshot (it's the raw
bytes — HTML/CSV/XLSX/PDF). Diff what `parse()` expects against what the live
page now provides (renamed columns, moved table, changed selector, new header
row, encoding shift, etc.). Reuse the shared coercers in
`warn_v2/scrapers/_helpers.py` rather than reinventing date/int/string parsing.

### 3. Fix `parse()`

Edit the parser so it handles the live structure **and** still parses the golden
fixture. Re-run step 1 against the live source until `VALIDATE ok=True`. If the
live source itself is the moving target, replay your fix against the saved
snapshot the same way (swap `s.fetch()` for `open(snapshot,'rb').read()`).

### 4. Test

```bash
"$PY" -m pytest tests/test_<xx>.py -q     # the per-state test first
"$PY" -m pytest -q                        # then the full suite
```

Both must be green. (Some pandas-touching tests can fail locally under Windows
Smart App Control — see README; if so, lean on the GitHub Actions run, but a
broken *scraper* test is on you.)

### 5. Open a PR (never merge)

```bash
# Don't open a duplicate — this replaces the old 12h heal cooldown:
gh pr list --state open --search "scraper XX" --json number,title
```

If an open PR already exists for `XX`, stop and report it. Otherwise:

- Branch: `fix/scraper-XX-<yyyymmdd>`
- Commit: `fix(scraper): repair XX parser` (+ a one-line cause in the body)
- PR body: the original failure (error / row counts vs `expected_row_range`),
  the root cause (what the source changed), and what you changed. Note this is
  app-code only — no chart version bump (see `CLAUDE.md`).

### 6. Summarize

One line per state: `fixed (PR #N)` / `ok (no change)` / `skipped (fetch_failed)`
/ `existing PR #N`. End with a short roll-up.

---

## Running this as a loop or routine

- **One state, interactively:** `/heal-scraper CA`
- **Sweep all states, self-paced:** `/loop /heal-scraper`
- **Re-check on an interval:** `/loop 6h /heal-scraper`

### Unattended local scheduled task

The op needs only the local venv, `git`, and `gh` — no cluster access (it
reproduces live). Run it headless on the dev machine shortly after the nightly
prod scrape (`17 7 * * *`). Windows Task Scheduler example (daily 08:30):

```powershell
$claude = (Get-Command claude).Source
$action = New-ScheduledTaskAction -Execute $claude `
  -Argument '-p "/heal-scraper" --permission-mode acceptEdits' `
  -WorkingDirectory 'C:\Users\rapha\workspace\warn_scraper_v2'
$trigger = New-ScheduledTaskTrigger -Daily -At 8:30am
Register-ScheduledTask -TaskName 'warn-heal-scraper' -Action $action -Trigger $trigger
```

Output is draft PRs for human review — nothing deploys until you merge. Validate
the headless `claude -p "/heal-scraper"` invocation once interactively before
trusting the scheduled run; confirm `gh` auth resolves non-interactively in that
context (the `GH_TOKEN` shim above).

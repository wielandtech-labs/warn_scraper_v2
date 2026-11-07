# Repairing a broken scraper

When a scraper's `parse()` or `validate()` step fails, the runner saves the raw
response as a **snapshot** (`warn_v2/pipeline/runner.py`) and records the failure
in `scraper_runs`. That snapshot is replay material: the fetch/parse split means
a fixed `parse()` can be re-run against the exact bytes that broke it.

Repair is a **Claude Code op**, not an in-app agent — the
[`/heal-scraper`](../.claude/commands/heal-scraper.md) slash command in this repo.
(The earlier in-app self-heal loop under `warn_v2/heal/` was removed 2026-06-19;
it reinvented, inside the app, what Claude Code already does natively with a
human reviewing the PR.)

**What the op does**, per target state:

1. **Reproduces the break live, locally** — runs the state's `fetch()` + `parse()`
   and the same `validate()` gate the runner uses (`expected_row_range` +
   `required_fields`), with no DB or cluster access. A `fetch()` network error is
   treated as transient and skipped; a `parse()`/`validate()` failure is a real
   break.
2. Reads the scraper module (`warn_v2/scrapers/states/<xx>.py`) and the golden
   fixture (`warn_v2/scrapers/fixtures/<xx>/`), and fixes `parse()` so it handles
   the live page **and** still passes the golden fixture.
3. Runs the test suite, then opens a PR for human review (it never merges —
   merging `main` is a production deploy). Before opening, it checks for an
   existing PR for that state so a repeated run doesn't duplicate it.

**Running it:**

```text
/heal-scraper CA          # repair one state, interactively in Claude Code
/loop /heal-scraper       # sweep all states, self-paced
/loop 6h /heal-scraper    # re-check on an interval
```

For unattended runs, a local Windows Task Scheduler entry (or WSL cron) launches
Claude Code headless shortly after the nightly scrape — see
[`.claude/commands/heal-scraper.md`](../.claude/commands/heal-scraper.md) for the
scheduled-task recipe. The op needs only `git`/`gh` and the local venv; no
cluster access (reproduction is live), so it runs fine off the dev machine.

**Environment:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `SNAPSHOT_DIR` | `./snapshots` | Where the runner writes raw failure snapshots (replay material) |

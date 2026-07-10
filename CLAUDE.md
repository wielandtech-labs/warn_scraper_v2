# CLAUDE.md

## Repo overview

`warn_scrapper_v2` — WARN Act layoff-notice scraper. 48 jurisdictions live.
K3s deployment via Flux + Helm chart in `charts/warn-v2/`.

## Helm chart version (`charts/warn-v2/Chart.yaml`)

**Only bump `version:` when the chart itself changes**, i.e. when you modify
anything under `charts/warn-v2/` (templates, `values.yaml`, `Chart.yaml`).

Do **not** bump for application-code-only changes (`warn_v2/`, `tests/`, etc.).
Those deploy via the image tag path:

```
PR merges → CI builds new image → new tag pushed to GHCR
→ Flux ImageUpdateAutomation detects new tag
→ pushes to flux/image-updates/prod branch
→ auto-merge GHA workflow merges to main
→ Flux sees updated values.image.tag → Helm upgrade → new pods
```

The HelmRelease uses a **GitRepository source** (not a chart museum), so Flux
reconciles on image-tag value changes — a chart version bump is not needed to
trigger deployment of new application code.

**Bump chart version when:** templates change, new values keys added, chart
dependencies change, or chart metadata changes.

**Do not bump when:** only `warn_v2/`, `tests/`, scripts, or docs change.

**Version collisions silently drop template changes.** Flux packages the chart
with `reconcileStrategy: ChartVersion`: if `version:` doesn't change, the chart
is NOT repackaged and your template edits never deploy — Helm keeps rendering
the old template with the new values (seen 2026-07-02: two PRs both targeted
0.1.21; a rebase deduped the identical bump, and the second PR's new CronJob
arg never rendered despite `Ready=True` everywhere). **Before merging a chart
PR, re-check that its `version:` is strictly greater than current `main`'s** —
if another chart PR merged first, bump again on top.

## Cluster access

- `kubectl` / `flux` live in WSL — prefix all commands with `wsl` from PowerShell.
- Credentials: always passed via `secretKeyRef` in pod specs — never decoded in transcript.
- `DATABASE_URL` secret: name `warn-v2-db`, key `url`.
- One-off Jobs: use `command: ["uv","run","python","-c"]` for inline python (plain
  `python` lacks deps); use `args: ["subcommand"]` for CLI entrypoints.
  Always clean up Jobs after.

## GitOps rules (mirrors w_homelab CLAUDE.md)

Make infrastructure changes in the repo, commit, and push. Do not apply
manifests directly to the cluster unless the user explicitly asks for a
break-glass operation.

## Ruff

Ruff is pinned exactly in `pyproject.toml` (dev extras) so lint results don't
drift when a new ruff release ships new rules. To upgrade: bump the pin, run
`uv lock`, and fix any new findings in the **same PR** (CI runs
`ruff check .` repo-wide, so new rules surface in files the PR doesn't
otherwise touch).

## Test suite

Run with: `cd warn_scrapper_v2 && .venv\Scripts\pytest` (uv not on PATH here;
use the local venv). All 500+ tests should pass with 0 failures before opening
a PR.

From a git worktree (which has no `.venv` of its own): run
`C:\Users\rapha\workspace\warn_scrapper_v2\.venv\Scripts\python.exe -m pytest`
with the worktree as cwd — `-m` puts the cwd first on `sys.path`, so the
worktree's `warn_v2` shadows the venv's editable install and the worktree code
is what actually gets tested (verify once with
`python -c "import warn_v2; print(warn_v2.__file__)"`).

Same trap for one-off scripts: `python some_script.py` puts the *script's*
directory first on `sys.path`, so `warn_v2` silently resolves to the venv's
editable install of the main checkout — old code, no error. From a worktree,
run scripts with `PYTHONPATH=<worktree>` (or via `python -m`).

## Database migrations (Alembic)

Create migrations **only** with `uv run alembic revision [--autogenerate] -m "..."`.
Never hand-author a migration file, and never pick the revision id or a
sequential number yourself — Alembic generates a random id + a
`YYYYMMDD_<rev>_<slug>.py` filename. Hand-incrementing the old `0014`/hex pattern
is what produced duplicate revision ids → a dual Alembic head that broke a prod
deploy. CI (`Alembic single head` step) fails on >1 head; resolve parallel heads
with `uv run alembic merge heads -m "..."`. Postgres-only DDL must be guarded
with a dialect check (tests use SQLite via `create_all`). See
`warn_v2/db/migrations/README`.

Autogenerate needs a live DB at head to diff against, and `alembic upgrade head`
does NOT run on SQLite (an old migration has an unguarded `ALTER COLUMN ... TYPE`).
Workaround for a new-table migration without touching prod: point DATABASE_URL at
a scratch SQLite file, `Base.metadata.create_all(engine)` then `drop()` the new
model's table, `alembic stamp head`, then `alembic revision --autogenerate` —
the diff contains exactly the new table.

## Production gate

Merging to main is a production deploy (the image-tag chain above runs
unattended). No dev/QA tier exists for this app — verify locally and run
`/code-review` before merging. Rollback = revert the image tag in
`wielandtech-labs/w_homelab` `clusters/prod/apps/warn-v2/` via PR.

# CLAUDE.md

## Repo overview

`warn_scrapper_v2` — WARN Act layoff-notice scraper. 46 jurisdictions live.
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

## Production gate

Merging to main is a production deploy (the image-tag chain above runs
unattended). No dev/QA tier exists for this app — verify locally and run
`/code-review` before merging. Rollback = revert the image tag in
`wielandtech-labs/w_homelab` `clusters/prod/apps/warn-v2/` via PR.

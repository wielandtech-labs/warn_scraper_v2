# WARN Scraper V2

AI-assisted rebuild of [warn_scrapper](https://wielandtech.com) (2022). Collects state WARN layoff notices, enriches each company via LLM + free public sources, and self-heals when a state's site reformats.

## Why V2

V1 had ~33 hand-written per-state scrapers that broke every time a state site reformatted, plus a Selenium-based D&B Hoover's enrichment scraper that was the main source of bad data. V2 keeps the original "Headhunter" goal — surface workers ~60 days before layoff — but moves the maintenance burden onto a self-healing loop.

## Architecture

```
CronJob (K3s) ──▶ Scraper runner ──▶ Postgres (CloudNativePG)
                       │
            parse fail │                 ┌──▶ Enrichment worker (Claude + web search)
                       ▼                 │
              Self-heal agent            └──▶ FastAPI + CSV/Sheet export
              (Claude Agent SDK)
              opens PR for review
```

See the [design plan](https://github.com/wielandtech) for full details (kept locally in `~/.claude/plans/`).

## Quick start

```powershell
# Core scraping + tests
uv sync --extra dev
uv run python -m pytest
uv run warn-v2 scrape --state CA

# Self-heal agent (requires ANTHROPIC_API_KEY)
uv run warn-v2 heal --state IA          # heal one broken state
uv run warn-v2 heal --all               # heal every state with a recent DB failure
uv run warn-v2 heal --all --dry-run     # rehearse without opening PRs

# Enrichment agent (requires ANTHROPIC_API_KEY)
uv run warn-v2 enrich                   # enrich up to 50 unenriched companies
uv run warn-v2 enrich --state CA        # only companies from CA notices
uv run warn-v2 enrich --rerun-below 0.7 # re-enrich low-confidence rows
uv run warn-v2 enrich --dry-run         # run agent but don't write to DB

# API + SPA (Phase 5 + 6) — single process, single port
uv run warn-v2 serve                    # FastAPI + bundled SPA on :8000
uv run warn-v2 backfill-geo             # populate locations.lat/lon from ZIP centroids

# Frontend dev (separate from python — requires node 20)
cd frontend && npm install && npm run dev   # Vite dev server on :5173, proxies to :8000
```

### Note on local testing under Windows Smart App Control

Smart App Control (SAC) on Windows blocks unsigned native extensions; some
wheels (numpy, pandas) ship `.pyd` binaries that SAC rejects, so the pandas-
touching tests fail locally with an "Application Control policy has blocked
this file" `ImportError`. The non-pandas tests (`tests/test_dedup.py`,
`tests/test_validate.py`, `tests/test_storage.py`) all run fine locally.

The full suite runs in GitHub Actions (Linux), which is the canonical
verification environment since production runs in K3s containers anyway. To
run the full suite locally either turn SAC off (one-way; not recommended),
install WSL2 (`wsl --install`), or build and `docker run` the image.

## Repo layout

| Path | Purpose |
|------|---------|
| `warn_v2/scrapers/base.py` | `StateScraper` Protocol + `NoticeRow` |
| `warn_v2/scrapers/states/{state}.py` | One module per state |
| `warn_v2/scrapers/fixtures/{state}/` | Golden samples + expected counts |
| `warn_v2/pipeline/` | runner, validate, dedup, storage |
| `warn_v2/enrichment/` | Claude-driven company enrichment |
| `warn_v2/heal/` | Self-heal agent + GitHub PR opener |
| `warn_v2/api/` | FastAPI read-only API |
| `warn_v2/db/` | SQLAlchemy models + Alembic |
| `charts/warn-v2/` | Helm chart for K3s deploy via Flux |

## Status

- [x] Phase 0 — scaffold + first state (CA)
- [x] Phase 1 — 5 representative states (CA, TX, NY, FL, WA)
- [x] Phase 2 — self-heal agent (**334 tests** as of 2026-05-28)
- [x] Phase 3 — bulk-port remaining states (46 jurisdictions)
- [x] **Production deployment live** (K3s via Flux, CloudNativePG, 2026-05-26)
- [x] Phase 4 — enrichment agent (Claude + web search, runs every 6 h)
- [x] Phase 5 — API + Grafana + AlertManager
- [x] Phase 6 — React SPA (dashboard, notices, companies, map, stats)

### Production deployment (as of 2026-05-26)

The scraper runs in a K3s homelab cluster managed by Flux GitOps (see
`w_homelab` repo at `wielandtech/w_homelab`).

**Infrastructure stack:**
- **Image**: `ghcr.io/wielandtech-labs/warn-v2` — built by `.github/workflows/docker.yml`,
  tagged `YYYYMMDD-HHMMSS-{sha}` for Flux Image Automation auto-upgrades
- **GitOps source**: `GitRepository` → `HelmRelease` using `charts/warn-v2`
  from this repo directly (not an OCI/HelmRepository)
- **Database**: shared CloudNativePG `postgres-cluster` in the `database` namespace;
  app uses `postgres-cluster-rw.database.svc.cluster.local:5432/warn_v2`
- **Alembic**: initial migration (`revision a1b2c3d4e5f6`) ran 2026-05-26;
  all four tables live (`locations`, `companies`, `notices`, `scraper_runs`)
- **CronJobs**: `warn-v2-warn-v2-scraper` runs daily at 07:17 (`scrape-all`); `warn-v2-warn-v2-enricher` runs every 6 h at `:23` (`enrich`, 50 companies/run, 30 s between companies)
- **Snapshots PVC**: `synostorage-iscsi-retain`, 10 Gi, mounted at `/var/snapshots`

**Secrets in `warn-v2` namespace** (all SealedSecrets, reconciled by Flux):

| Secret | Key | Env var |
|--------|-----|---------|
| `warn-v2-db` | `url` | `DATABASE_URL` |
| `warn-v2-anthropic` | `api-key` | `ANTHROPIC_API_KEY` |
| `warn-v2-github` | `token` | `GITHUB_TOKEN` |

> **Password rule**: `DATABASE_URL` must contain only URL-safe characters.
> Use `openssl rand -hex 20` to generate the Postgres role password — never
> a random generator that can produce `@`, `/`, `+`, or `=` in output.
> On the k3s cluster, use `~/.local/bin/kubeseal` (v0.37.0, installed 2026-05-26).

**Known issues as of 2026-05-27:**

- **GA**: `tcsg.edu/warn-public-view/` page sometimes doesn't settle to networkidle
  in under 60 s; scraper now uses `wait_until="load"` + `wait_for_selector("table")`.
- **MA**: mass.gov CSV endpoints reject plain httpx (403); scraper now downloads
  CSVs via the Playwright browser context so session cookies are shared.
- **TN**: `tn.gov` resets TLS from container/server IPs; scraper is written but
  `register()` is commented out. Re-enable with a proxy or residential IP.

**Running a one-off migration or scrape on the cluster:**

```bash
# Alembic upgrade (run from a shell with kubectl access)
kubectl run alembic-init -n warn-v2 \
  --image=ghcr.io/wielandtech-labs/warn-v2:LATEST_TAG \
  --restart=Never \
  --overrides='{
    "spec":{"containers":[{
      "name":"alembic-init",
      "image":"ghcr.io/wielandtech-labs/warn-v2:LATEST_TAG",
      "command":["uv","run","alembic","upgrade","head"],
      "env":[{"name":"DATABASE_URL","valueFrom":{"secretKeyRef":{"name":"warn-v2-db","key":"url"}}}]
    }]}
  }'

# Manual scrape for one state
kubectl create job --from=cronjob/warn-v2-warn-v2-scraper manual-$(date +%s) -n warn-v2

# Or targeted:
kubectl run scrape-tx -n warn-v2 \
  --image=ghcr.io/wielandtech-labs/warn-v2:LATEST_TAG \
  --restart=Never \
  --overrides='{
    "spec":{"containers":[{
      "name":"scrape-tx",
      "image":"ghcr.io/wielandtech-labs/warn-v2:LATEST_TAG",
      "command":["uv","run","warn-v2","scrape-all","--states","TX"],
      "env":[
        {"name":"DATABASE_URL","valueFrom":{"secretKeyRef":{"name":"warn-v2-db","key":"url"}}},
        {"name":"ANTHROPIC_API_KEY","valueFrom":{"secretKeyRef":{"name":"warn-v2-anthropic","key":"api-key"}}},
        {"name":"SNAPSHOT_DIR","value":"/tmp"}
      ]
    }]}
  }'
```

### Phase 3 coverage

46 jurisdictions implemented (45 states + DC):

| Implemented | Deferred |
|-------------|---------|
| AK, AL, AZ, CA, CO, CT, DC, DE, FL, GA, HI, IA, ID, IL, IN, KS, KY, LA, MA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NV, NY, OH, OR, PA, RI, SC, SD, TX, UT, VA, VT, WA, WI, WV | AR, NH, WY (no public data) · OK (Salesforce/Aura auth) · TN (container TLS block) |

See [`docs/deferred-states.md`](docs/deferred-states.md) for investigation notes on each deferred state.

### Phase 2: Self-heal agent

When a scraper's `parse()` or `validate()` step fails, the runner saves the raw
response as a **snapshot** and records the failure in `scraper_runs`. A separate
heal CronJob (or a manual `warn-v2 heal` invocation) detects these failures and
runs an agent loop to fix them autonomously.

**How it works:**

1. `warn_v2/heal/detector.py` — queries `scraper_runs` for recent
   `parse_failed` / `validation_failed` rows that still have a snapshot on disk
   and haven't been healed within the cooldown window (default 12 h).
2. `warn_v2/heal/agent.py` — a multi-turn Claude loop.  The agent has five
   tools: `read_parser` (current scraper source), `read_snapshot` (the failing
   raw input), `read_golden_fixture` (last-known-good sample), 
   `run_parser_candidate` (sandbox-executes a proposed fix), and `propose_patch`
   (terminal tool that ends the loop and hands back the fixed code).
3. `warn_v2/heal/sandbox.py` — runs candidate code in a subprocess with a
   timeout so a broken parser can't hang or crash the agent process.
4. `warn_v2/heal/github.py` — creates a branch, commits the patched module, and
   opens a PR via `gh`.  A human merges; the agent never auto-merges.

**Triggering heal:**

```powershell
# Heal a single state using the latest failure snapshot from the DB
warn-v2 heal --state IA

# Point at a specific snapshot (useful when DB is unavailable)
warn-v2 heal --state IA --snapshot ./snapshots/IA/20260522T060000_a1b2c3d4.bin

# Batch mode — heal every state with a recent unhealed failure
warn-v2 heal --all

# Dry-run: run the agent and prepare the patch but don't push or open a PR
warn-v2 heal --all --dry-run
```

**Environment variables:**

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | *(required)* | Anthropic API key for the Claude model |
| `SNAPSHOT_DIR` | `./snapshots` | Where the runner writes raw failure snapshots |

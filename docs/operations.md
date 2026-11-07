# Operations

How WARN Index runs in production, plus local-development notes. Moved out of
the README; the deployment notes are dated and some details have since
changed (the Helm chart's `values.yaml` and the prod HelmRelease in
`wielandtech-labs/w_homelab` are the source of truth for schedules and sizes).

## Build phases

- [x] Phase 0 — scaffold + first state (CA)
- [x] Phase 1 — 5 representative states (CA, TX, NY, FL, WA)
- [x] Phase 2 — replayable failure snapshots + repair workflow (the original in-app self-heal agent was retired 2026-06-19 in favor of the Claude Code `/heal-scraper` op)
- [x] Phase 3 — bulk-port remaining states (46 jurisdictions)
- [x] **Production deployment live** (K3s via Flux, CloudNativePG, 2026-05-26)
- [x] Phase 4 — enrichment agent (Claude + web search, runs every 6 h)
- [x] Phase 5 — API + Grafana + AlertManager
- [x] Phase 6 — React SPA (dashboard, notices, companies, map, stats)

## Production deployment (as of 2026-05-26)

The scraper runs in a K3s homelab cluster managed by Flux GitOps (see
`w_homelab` repo at `wielandtech-labs/w_homelab`).

**Infrastructure stack:**
- **Image**: `ghcr.io/wielandtech-labs/warn-v2` — built by `.github/workflows/docker.yml`,
  tagged `YYYYMMDD-HHMMSS-{sha}` for Flux Image Automation auto-upgrades
- **GitOps source**: `GitRepository` → `HelmRelease` using `charts/warn-v2`
  from this repo directly (not an OCI/HelmRepository)
- **Database**: shared CloudNativePG `postgres-cluster` in the `database` namespace;
  app uses `postgres-cluster-rw.database.svc.cluster.local:5432/warn_v2`
- **Alembic**: initial migration (`revision a1b2c3d4e5f6`) ran 2026-05-26;
  all four tables live (`locations`, `companies`, `notices`, `scraper_runs`)
- **CronJobs**: `warn-v2-warn-v2-scraper` runs daily at 07:17 (`scrape-all`); `warn-v2-warn-v2-enricher` runs every 6 h at `:23` (`enrich`, 50 companies/run, 30 s between companies); `warn-v2-warn-v2-cross-check` (opt-in via `crossCheck.enabled`) runs daily at 09:17 (`cross-check`), re-fetching each state's live WARN page and recording drift vs. stored notices to `cross_check_runs`; `warn-v2-warn-v2-sentiment-report` runs weekly Mon 02:07 (`sentiment-report`, see [Sentiment reports](analytics.md#sentiment-reports--industry-scorecards)); `warn-v2-warn-v2-bls` (opt-in via `bls.enabled`) runs weekly Wed 12:40 (`fetch-bls`, see [Economic indicators](analytics.md#economic-indicators))
- **Snapshots PVC**: `synostorage-iscsi-retain`, 10 Gi, mounted at `/var/snapshots`

**Secrets in `warn-v2` namespace** (all SealedSecrets, reconciled by Flux):

| Secret | Key | Env var |
|--------|-----|---------|
| `warn-v2-db` | `url` | `DATABASE_URL` |
| `warn-v2-anthropic` | `api-key` | `ANTHROPIC_API_KEY` |

> **Password rule**: `DATABASE_URL` must contain only URL-safe characters.
> Use `openssl rand -hex 20` to generate the Postgres role password — never
> a random generator that can produce `@`, `/`, `+`, or `=` in output.
> On the k3s cluster, use `~/.local/bin/kubeseal` (v0.37.0, installed 2026-05-26).

**Known issues as of 2026-05-27:**

- **GA**: `tcsg.edu/warn-public-view/` page sometimes doesn't settle to networkidle
  in under 60 s; scraper now uses `wait_until="load"` + `wait_for_selector("table")`.
- **MA**: mass.gov CSV endpoints reject plain httpx (403); scraper now downloads
  CSVs via the Playwright browser context so session cookies are shared.
- **TN** *(resolved 2026-06-26, PR #88)*: `tn.gov`'s WAF resets TLS connections
  for non-browser fingerprints; scraper now fetches via `curl_cffi`
  (`impersonate="chrome"`) with a short retry loop (the WAF still RSTs ~1 in 4
  handshakes). No proxy needed.

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

## Coverage

48 jurisdictions implemented (47 states + DC):

| Implemented | Deferred |
|-------------|---------|
| AK, AL, AZ, CA, CO, CT, DC, DE, FL, GA, HI, IA, ID, IL, IN, KS, KY, LA, MA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NJ, NM, NV, NY, OH, OK, OR, PA, RI, SC, SD, TN, TX, UT, VA, VT, WA, WI, WV | AR, NH, WY (no public data) |

See [`docs/deferred-states.md`](deferred-states.md) for investigation notes on each deferred state, and [`docs/ROADMAP.md`](ROADMAP.md) for the agent-executable work tracks (healing, backfills, records requests, enrichment).

## Local testing under Windows Smart App Control

Smart App Control (SAC) on Windows blocks unsigned native extensions; some
wheels (numpy, pandas) ship `.pyd` binaries that SAC rejects, so the pandas-
touching tests fail locally with an "Application Control policy has blocked
this file" `ImportError`. The non-pandas tests (`tests/test_dedup.py`,
`tests/test_validate.py`, `tests/test_storage.py`) all run fine locally.

The full suite runs in GitHub Actions (Linux), which is the canonical
verification environment since production runs in K3s containers anyway. To
run the full suite locally either turn SAC off (one-way; not recommended),
install WSL2 (`wsl --install`), or build and `docker run` the image.

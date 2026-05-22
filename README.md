# WARN Scraper V2

AI-assisted rebuild of [warn_scrapper](https://wielandtech.com) (2022). Collects state WARN layoff notices, enriches each company via LLM + free public sources, and self-heals when a state's site reformats.

## Why V2

V1 had ~33 hand-written per-state scrapers that broke every time a state site reformatted, plus a Selenium-based the provider enrichment scraper that was the main source of bad data. V2 keeps the original "Headhunter" goal — surface workers ~60 days before layoff — but moves the maintenance burden onto a self-healing loop.

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
uv sync --extra dev
uv run python -m pytest
uv run warn-v2 scrape --state CA
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
- [ ] Phase 2 — self-heal agent
- [x] Phase 3 — bulk-port remaining states (**39 jurisdictions, 212 tests** as of 2026-05-22)
- [ ] Phase 4 — enrichment agent
- [ ] Phase 5 — API + Grafana + AlertManager

### Phase 3 coverage

39 jurisdictions implemented (38 states + DC):

| Implemented | Deferred |
|-------------|---------|
| AK, AL, AZ, CA, CO, CT, DC, DE, FL, HI, IA, ID, IL, IN, KS, KY, LA, MD, ME, MS, MT, NC, ND, NE, NJ, NM, NV, NY, OK, OR, RI, SC, SD, TN, TX, UT, VA, VT, WA, WI | GA, MA, MI, MN, MO, OH, PA (JS-rendered / bot-blocked) · AR, NH, WY (no public data) · WV (unstructured PDFs) |

See [`docs/deferred-states.md`](docs/deferred-states.md) for investigation notes on each deferred state.

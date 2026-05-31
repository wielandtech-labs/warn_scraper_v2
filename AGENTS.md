# AGENTS.md — operational notes for Claude agents

Project-specific guidance that doesn't belong in the README. Update this file
when you discover a gotcha, a non-obvious resource constraint, or a "we already
tried that" finding.

---

## Kubernetes access

`kubectl` is not configured in the Windows shell but works via WSL:

```bash
wsl kubectl get nodes
wsl kubectl apply -f - -n warn-v2 <<'EOF'
...
EOF
wsl kubectl logs -n warn-v2 -l job-name=my-job -f
```

All `kubectl` commands in this project should be prefixed with `wsl`.

---

## Kubernetes / one-off jobs

### Memory requirements for `backfill-historical`

| State | Minimum memory | Notes |
|-------|---------------|-------|
| CA    | **2Gi**       | CA EDD publishes large fiscal-year PDFs (one file per FY covering 1 000 + rows). pdfplumber / pymupdf hold the whole file in memory during parse. 512 Mi is OOMKilled. |
| All others | 512 Mi | Default job limit is sufficient. |

Example pod spec override for CA:

```yaml
resources:
  requests:
    memory: 1Gi
  limits:
    memory: 2Gi
```

### iSCSI PVC node affinity

The `synostorage-iscsi-retain` storage class creates PVCs that bind to a single
node (`wtech7063`). Any pod that mounts the PDF PVC
(`warn-v2-warn-v2-pdfs`) will be scheduled on that node. This is fine on the
current single-effective-node setup; revisit if the cluster grows.

---

## `warn-v2 backfill-geo`

Populates or upgrades `locations.lat/lon` using the best available source.

```
warn-v2 backfill-geo                        # fill NULL coordinates only
warn-v2 backfill-geo --rerun-address        # also upgrade ZIP/city centroids to Census street-level
warn-v2 backfill-geo --state GA             # limit to one state
warn-v2 backfill-geo --dry-run              # preview without writing
```

**Geocoding priority** (per location, in order):
1. Census street geocoder — requires a non-null `notice.address` linked to the location
2. ZIP centroid — fast local lookup, ~city-block radius
3. City centroid — ~11 km accuracy, for city-only records
4. County centroid — last resort (~30 km)

**`--rerun-address` mode** calls only the Census geocoder (Tier 1). If Census
can't resolve the address, existing coordinates are kept — no ZIP-centroid
regression. Use this after a new enricher populates `notice.address` for a
state that previously had only centroid-level coordinates.

**When to run:**
- After `enrich-ga` (or any enricher that backfills `notice.address`) to upgrade affected locations.
- After adding a new state whose scraper now extracts addresses.
- Periodically with `--rerun-address` to pick up any newly enriched addresses across all states.

**Stats output:**

| Field | Meaning |
|-------|---------|
| `upgraded` | Had coordinates; upgraded to Census street-level via address |
| `filled_address` | Was NULL; filled via Census geocoder |
| `filled_zip` | Was NULL; filled via ZIP/city/county centroid |
| `no_coords` | No geocoding source resolved — coordinates still NULL |
| `skipped_no_address` | `--rerun-address` mode: location has coords but no linked address (or Census returned nothing) |

**GA-specific note (May 2026):** TCSG `Company Address` is sometimes the
corporate HQ address (non-GA state). Those locations get `skipped_no_address`
because Census returns no match for a non-GA address with `state=GA`. Their
ZIP centroids are preserved, which is the correct fallback.

---

## SQLAlchemy / `backfill_geo.py`

`yield_per` controls the DB fetch batch size but does **not** bound the
SQLAlchemy identity map. Every object loaded into the session accumulates in
memory until explicitly expunged. The backfill loop uses `try/finally` +
`session.expunge(obj)` after each row to keep memory bounded. Always call
`session.flush()` **before** `session.expunge()` — expunging with unflushed
changes silently discards them.

---

## Multi-year backfill idempotency

`warn-v2 backfill-historical --state <ST>` is safe to re-run. Rows are upserted
on `notice_id`; `rows_new=0` just means the data was already present. CO is
excluded because its Google Sheets export is already cumulative (all years in
one sheet).

---

## PDF streaming endpoint

`GET /api/notices/{id}/pdf` streams the file from the PVC via FastAPI
`FileResponse`. A HEAD request returns `content-type: text/html` (Starlette
quirk) — the GET response correctly returns `application/pdf`. Confirmed by
inspecting the first bytes of the body (`%PDF-1.6%`). Not a bug.

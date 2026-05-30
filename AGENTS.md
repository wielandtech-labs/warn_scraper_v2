# AGENTS.md — operational notes for Claude agents

Project-specific guidance that doesn't belong in the README. Update this file
when you discover a gotcha, a non-obvious resource constraint, or a "we already
tried that" finding.

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

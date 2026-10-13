"""One profile per raw Company row: its name variants and what its notices say.

The matcher compares profiles, never the enrichment fields (unique id,
website, parents, NAICS, headcount). The weak labels come from the same
enrichment, and unenriched companies, the ones the heuristics miss, don't
have them. Those fields ride along in ENRICHMENT_COLUMNS only so labels.py and
the baseline can read them; features.py must not (a test enforces it).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.companies.normalize import canonical_name, cleaned_key, dba_name, website_domain
from warn_v2.db.models import Company, Location, Notice

ENRICHMENT_COLUMNS = ["unique_id", "website_domain", "current_canonical_id",
                      "enriched", "enrichment_confidence", "n_notices_all"]
MAX_ADDRESSES = 3  # kept for the labelling CSV only
MAX_POINTS = 25


def _dba_key(name: str) -> str:
    d = dba_name(name)
    return canonical_name(d) if d else ""


def build_profiles(companies: pd.DataFrame, notices: pd.DataFrame) -> pd.DataFrame:
    """Profiles from plain frames (the DB loader and tests both land here).

    companies: id, name, unique_id, website, canonical_company_id, and
               optionally enriched_at, enrichment_confidence
    notices:   company_id, state, notice_date, layoff_count, city, zip, lat,
               lon, address (location columns may be null)

    One row per company, indexed 0..n-1, in `id` order.
    """
    companies = companies.sort_values("id").reset_index(drop=True)
    by_co: dict[int, list[Any]] = defaultdict(list)
    for r in notices.itertuples(index=False):
        if pd.notna(r.company_id):
            by_co[int(r.company_id)].append(r)

    rows = []
    for c in companies.itertuples(index=False):
        ns = by_co.get(int(c.id), [])
        states = frozenset(str(n.state) for n in ns)
        dates = np.sort(np.array(
            [np.datetime64(pd.Timestamp(n.notice_date).date(), "D")
             for n in ns if pd.notna(n.notice_date)], dtype="datetime64[D]"))
        counts = [float(n.layoff_count) for n in ns
                  if pd.notna(n.layoff_count) and 0 < n.layoff_count <= 50_000]
        pts = [(float(n.lat), float(n.lon)) for n in ns
               if pd.notna(n.lat) and pd.notna(n.lon)][:MAX_POINTS]
        addrs = []
        for n in ns:
            a = n.address if isinstance(n.address, str) else None
            if a and a not in addrs:
                addrs.append(a)
            if len(addrs) >= MAX_ADDRESSES:
                break
        name = str(c.name)
        rows.append({
            "company_id": int(c.id),
            "name": name,
            "canonical": canonical_name(name),
            "cleaned": cleaned_key(name),
            "dba": _dba_key(name),
            "n_notices": len(ns),
            "states": states,
            "cities": frozenset(
                f"{n.state}|{str(n.city).strip().lower()}" for n in ns
                if isinstance(n.city, str) and n.city.strip()),
            "zips": frozenset(str(n.zip)[:5] for n in ns
                              if isinstance(n.zip, str) and n.zip.strip()),
            "points": np.array(pts, dtype=float).reshape(-1, 2),
            "dates": dates,
            "state_days": frozenset(
                (str(n.state), pd.Timestamp(n.notice_date).date()) for n in ns
                if pd.notna(n.notice_date)),
            "total_layoffs": float(sum(counts)),
            "addresses": tuple(addrs),
            "unique_id": c.unique_id if isinstance(c.unique_id, str) and c.unique_id else None,
            "website_domain": (website_domain(c.website) or None)
                              if isinstance(c.website, str) else None,
            "current_canonical_id": (int(c.canonical_company_id)
                                     if pd.notna(c.canonical_company_id) else None),
            "enriched": pd.notna(getattr(c, "enriched_at", None)),
            "enrichment_confidence": (float(conf) if pd.notna(
                conf := getattr(c, "enrichment_confidence", None)) else None),
        })
    out = pd.DataFrame(rows)
    # pandas infers a string dtype that turns None into NaN; downstream code
    # (and the consolidator's own helpers) expect None for "missing".
    for col in ("unique_id", "website_domain", "current_canonical_id",
                "enrichment_confidence"):
        if col in out:
            out[col] = out[col].astype(object).where(out[col].notna(), None)
    return out


def load_profiles(session: Session) -> pd.DataFrame:
    """Every Company row, with its live notices."""
    companies = pd.DataFrame(
        session.execute(select(
            Company.id, Company.name, Company.unique_id, Company.website,
            Company.canonical_company_id, Company.enriched_at, Company.enrichment_confidence,
        )).all(),
        columns=["id", "name", "unique_id", "website", "canonical_company_id",
                 "enriched_at", "enrichment_confidence"],
    )
    notices = pd.DataFrame(
        session.execute(
            select(
                Notice.company_id, Notice.state, Notice.notice_date, Notice.layoff_count,
                Location.city, Location.zip, Location.lat, Location.lon, Notice.address,
            )
            .outerjoin(Location, Notice.location_id == Location.id)
            .where(Notice.is_superseded.is_(False), Notice.company_id.is_not(None))
        ).all(),
        columns=["company_id", "state", "notice_date", "layoff_count",
                 "city", "zip", "lat", "lon", "address"],
    )
    prof = build_profiles(companies, notices)
    # All notices, superseded included: only the heuristic baseline's survivor
    # tie-break reads this (as the consolidator does), never a feature.
    all_counts = dict(session.execute(
        select(Notice.company_id, func.count(Notice.notice_id))
        .where(Notice.company_id.is_not(None)).group_by(Notice.company_id)
    ).all())
    prof["n_notices_all"] = prof["company_id"].map(lambda c: int(all_counts.get(c, 0)))
    return prof

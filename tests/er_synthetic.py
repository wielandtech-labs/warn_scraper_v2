"""Synthetic companies for the entity-resolution tests.

Each true entity appears as one to four Company rows whose names vary the
way WARN filings do: legal suffix, store number, site suffix, case, a typo,
or a dba clause. Its notices sit in one home state near one city, in one
date range. Half the entities are "enriched": most of their rows carry the
entity's unique id and website. Distractors share a first word with another
entity but are different companies elsewhere.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from warn_v2.ml.er.records import build_profiles

ADJ = ["Acme", "Summit", "Harbor", "Granite", "Pioneer", "Cascade", "Beacon", "Redwood",
       "Meridian", "Sterling", "Keystone", "Frontier", "Liberty", "Northstar", "Bluewater",
       "Ironwood", "Silverline", "Crescent", "Evergreen", "Highland"]
NOUN = ["Foods", "Logistics", "Packaging", "Health", "Steel", "Plastics", "Textiles",
        "Printing", "Dairy", "Furniture", "Electronics", "Bakery", "Motors", "Paper",
        "Glass", "Pharma", "Apparel", "Brewing", "Tools", "Freight"]
SUFFIX = ["Inc", "Corp", "LLC", "Company", "Corporation", "Incorporated"]
STATES = ["AA", "BB", "CC", "DD", "EE"]
CITIES = ["Springfield", "Riverton", "Fairview", "Lakeside", "Milltown", "Oakdale"]
MIDDLE = ["", "Valley", "Coastal", "National", "United", "Western", "Eastern", "Central",
          "Premier", "Allied", "Continental", "Mountain", "Prairie", "Delta", "Atlas",
          "Capitol", "Union", "Royal", "Golden", "Metro"]


def _variant(base: str, rng: np.random.Generator) -> str:
    kind = rng.integers(0, 6)
    if kind == 0:
        return f"{base} {rng.choice(SUFFIX)}"
    if kind == 1:
        return f"{base} #{rng.integers(100, 9999)}"
    if kind == 2:
        return f"{base} - {rng.choice(CITIES)} Plant"
    if kind == 3:
        return base.upper()
    if kind == 4 and len(base) > 6:
        k = int(rng.integers(1, len(base) - 2))
        return base[:k] + base[k + 1:]  # drop one character
    return f"{rng.choice(ADJ)} Holdings dba {base}"


def make(n_entities: int = 300, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """(companies frame, notices frame, true entity per company row)."""
    rng = np.random.default_rng(seed)
    names = [" ".join(t for t in (a, m, b) if t) for a in ADJ for m in MIDDLE for b in NOUN]
    rng.shuffle(names)
    # Sites are shared: every entity in a state files from one of its few
    # cities, each with a handful of ZIPs, so location alone can't identify it.
    geo = {(st, c): (30 + rng.random() * 15, -110 + rng.random() * 30)
           for st in STATES for c in CITIES}
    companies, notices, truth = [], [], []
    cid = 1
    for e in range(n_entities):
        base = names[e % len(names)]
        state = STATES[e % len(STATES)]
        city = CITIES[int(rng.integers(0, len(CITIES)))]
        lat, lon = geo[(state, city)]
        start = date(2010, 1, 1) + timedelta(days=int(rng.integers(0, 3000)))
        enriched = rng.random() < 0.5
        uid = f"{e:09d}" if enriched else None
        site = f"https://www.{base.lower().replace(' ', '')}.com" if enriched else None
        n_rows = int(rng.integers(1, 5))
        for r in range(n_rows):
            name = base + f" {rng.choice(SUFFIX)}" if r == 0 else _variant(base, rng)
            has_uid = enriched and rng.random() < 0.8
            companies.append({"id": cid, "name": name,
                              "unique_id": uid if has_uid else None,
                              "website": site if has_uid else None,
                              "canonical_company_id": None,
                              "enriched_at": "2026-01-01" if has_uid else None,
                              "enrichment_confidence": 0.9 if has_uid else None})
            truth.append(e)
            for _ in range(int(rng.integers(1, 5))):
                d = start + timedelta(days=int(rng.integers(0, 900)))
                notices.append({
                    "company_id": cid, "state": state, "notice_date": d,
                    "layoff_count": int(rng.integers(10, 300)), "city": city,
                    "zip": f"{10000 + CITIES.index(city) * 10 + int(rng.integers(0, 4)):05d}",
                    "lat": lat + rng.normal(0, 0.05), "lon": lon + rng.normal(0, 0.05),
                    "address": f"{rng.integers(1, 999)} Main St, {city}",
                })
            cid += 1
    return pd.DataFrame(companies), pd.DataFrame(notices), np.array(truth)


def profiles(n_entities: int = 300, seed: int = 0) -> tuple[pd.DataFrame, np.ndarray]:
    companies, notices, truth = make(n_entities, seed)
    return build_profiles(companies, notices), truth


def true_pairs(truth: np.ndarray) -> pd.DataFrame:
    rows = []
    for e in np.unique(truth):
        m = np.flatnonzero(truth == e)
        rows += [(int(m[x]), int(m[y])) for x in range(len(m)) for y in range(x + 1, len(m))]
    return pd.DataFrame(rows, columns=["a", "b"], dtype=int)

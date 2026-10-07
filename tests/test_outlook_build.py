"""build_outlook end to end on a seeded SQLite DB."""
from __future__ import annotations

import math
from datetime import date

import numpy as np

from warn_v2.db.models import BlsSeries, Company, Notice
from warn_v2.labor import catalog
from warn_v2.outlook.build import SETTLE_DAYS, build_outlook, settled_months
from warn_v2.outlook.panel import month_range, shift_month

AS_OF = date(2026, 10, 7)
STATES = ["CA", "TX", "NY", "FL", "WA", "OH"]


def _seed(db, *, rise_state="CA", with_bls=False):
    """~6 years of monthly notices per state. `rise_state` climbs 40%/yr over
    the trend window; the others are flat. With `with_bls`, each state's
    notices respond to its unemployment change (+20% per point, lagged)."""
    rng = np.random.default_rng(0)
    months = month_range("2020-09", "2026-08")
    factory = Company(name="Factory Co", naics_code="331110")
    grocer = Company(name="Grocer Co", naics_code="445110")
    db.add_all([factory, grocer])
    db.flush()
    seq = 0
    for st_i, st in enumerate(STATES):
        u3 = {}
        for i, m in enumerate(month_range("2019-01", "2026-09")):
            u3[m] = 4.0 + 1.5 * math.sin(i / 7.0 + st_i)
        if with_bls:
            sid = catalog.laus_state_series(st)
            db.add_all(BlsSeries(series_id=sid, period=m, value=v) for m, v in u3.items())
        for i, m in enumerate(months):
            lam = 20.0
            if st == rise_state:
                lam *= math.exp(math.log(1.4) * i / 12)
            if with_bls:
                x = u3[shift_month(m, -1)] - u3[shift_month(m, -13)]
                lam *= math.exp(math.log(1.2) * x)
            for _ in range(rng.poisson(lam)):
                seq += 1
                db.add(
                    Notice(
                        notice_id=f"ob_{seq}",
                        state=st,
                        employer=f"E{seq}",
                        notice_date=date(int(m[:4]), int(m[5:7]), 10),
                        layoff_count=50,
                        company_id=[None, factory.id, grocer.id][seq % 3],
                    )
                )
    # Superseded and Non-WARN rows never count.
    db.add(Notice(notice_id="ob_sup", state="TX", employer="S", notice_date=date(2026, 1, 5),
                  layoff_count=1, is_superseded=True))
    db.add(Notice(notice_id="ob_nw", state="TX", employer="N", notice_date=date(2026, 1, 5),
                  layoff_count=1, closure_category="Non-WARN"))
    db.flush()


def test_settled_months_drops_recent():
    months = month_range("2026-06", "2026-09")
    assert settled_months(months, date(2026, 10, 7)) == ["2026-06", "2026-07", "2026-08"]
    assert SETTLE_DAYS == 30
    assert settled_months(months, date(2026, 9, 30)) == ["2026-06", "2026-07"]


def test_planted_rise_is_the_top_trend(db):
    _seed(db)
    out = build_outlook(db, as_of=AS_OF)
    assert out["schema"] == 1
    assert out["window"] == {"first_month": "2023-09", "last_month": "2026-08", "months": 36}
    states = out["trends"]["states"]
    assert states[0]["code"] == "CA"
    assert states[0]["q"] < 0.05
    assert 20 < states[0]["pct_per_year"] < 60
    claim_ids = [c["id"] for c in out["claims"]]
    assert "state_trend:CA" in claim_ids
    firm = {c["subject"] for c in out["claims"] if c["confidence"] != "watch"}
    for row in states[1:]:
        assert row["code"] not in firm
    assert out["unemployment_link"] is None  # no BLS rows


def test_unemployment_link_recovers_planted_effect(db):
    _seed(db, rise_state=None, with_bls=True)
    link = build_outlook(db, as_of=AS_OF)["unemployment_link"]
    assert link is not None
    assert link["pooled"]["n_states"] == len(STATES)
    assert link["pooled"]["ci_lo_pct"] < 20 < link["pooled"]["ci_hi_pct"]


def test_sector_share_rows(db):
    _seed(db)
    sectors = build_outlook(db, as_of=AS_OF)["sectors"]
    # Classified notices alternate factory/grocer: both shares are flat ~50%.
    assert sorted(s["code"] for s in sectors) == ["31-33", "44-45"]
    for row in sectors:
        assert abs(row["t"]) < 3
        assert row["q"] > 0.05


def test_empty_db(db):
    out = build_outlook(db, as_of=AS_OF)
    assert out["trends"]["states"] == []
    assert out["sectors"] == []
    assert out["claims"] == []

"""Repeat-layoff dataset: event collapsing, labels, censoring, leakage."""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from tests.ml_synthetic import background, notices_frame, population
from warn_v2.db.models import Company, Notice
from warn_v2.ml.events import FEATURES, build_events, km_repeat_curve, load_notices

D0 = date(2015, 3, 2)
AS_OF = date(2020, 1, 1)
BG = background("AA", date(2013, 1, 1), date(2019, 12, 31))


def _events(rows, as_of=AS_OF, bg=BG):
    return build_events(notices_frame(rows + bg), as_of=as_of)


def _company(events, key="acme"):
    return events[events["company_key"] == key].reset_index(drop=True)


def test_multi_site_filings_collapse_into_one_event():
    rows = [
        {"company_key": "acme", "state": "AA", "notice_date": D0},
        {"company_key": "acme", "state": "BB", "notice_date": D0},  # 2nd site, same day
        {"company_key": "acme", "state": "AA", "notice_date": D0 + timedelta(days=10)},
        {"company_key": "acme", "state": "AA", "notice_date": D0 + timedelta(days=50)},
        {"company_key": "acme", "state": "AA", "notice_date": D0 + timedelta(days=400)},
    ]
    ev = _company(_events(rows))
    assert list(ev["t0"].dt.date) == [D0, D0 + timedelta(days=50), D0 + timedelta(days=400)]
    assert ev.loc[0, "day_notices"] == 2 and ev.loc[0, "day_states"] == 2
    # Day-10 notice is part of event 0 — not a repeat, and not a feature of it.
    assert list(ev["next_gap_days"].iloc[:2]) == [50, 350]
    assert list(ev["label"]) == [1, 1, 0]
    assert list(ev["prior_events"]) == [0, 1, 2]


def test_label_horizon_is_365_days():
    rows = [
        {"company_key": "acme", "state": "AA", "notice_date": D0},
        {"company_key": "acme", "state": "AA", "notice_date": D0 + timedelta(days=366)},
    ]
    assert _company(_events(rows)).loc[0, "label"] == 0


def test_open_horizon_is_censored():
    rows = [{"company_key": "acme", "state": "AA", "notice_date": date(2019, 6, 1)}]
    ev = _company(_events(rows))
    assert not ev.loc[0, "labelled"] and math.isnan(ev.loc[0, "label"])


def test_coverage_hole_in_horizon_is_not_labelled():
    # The state publishes nothing for three months: a "no repeat" there is
    # unobservable, not a negative.
    bg = background("AA", date(2013, 1, 1), date(2019, 12, 31),
                    skip_months={"2015-07", "2015-08", "2015-09"})
    rows = [{"company_key": "acme", "state": "AA", "notice_date": D0}]
    assert not _company(_events(rows, bg=bg)).loc[0, "labelled"]
    assert _company(_events(rows)).loc[0, "labelled"]


def test_exclusions_and_count_sanity():
    rows = [
        {"company_key": "ms", "state": "AA", "notice_date": D0, "closure_category": "Non-WARN"},
        {"company_key": "sc", "state": "SC", "notice_date": date(2016, 1, 1)},
        {"company_key": "big", "state": "AA", "notice_date": D0, "layoff_count": 900_000},
    ]
    ev = _events(rows)
    assert {"ms", "sc"}.isdisjoint(ev["company_key"])
    big = _company(ev, "big")
    assert big.loc[0, "day_count_missing"] == 1 and big.loc[0, "day_layoffs_log"] == 0


def test_features_never_read_the_future():
    """Truncating the data at T must not change any feature of an event that
    opened on or before T — only labels may differ."""
    full = population(n_companies=800)
    for cut in (date(2010, 6, 30), date(2016, 2, 14)):
        past = full[full["notice_date"] <= pd.Timestamp(cut)]
        a = build_events(full, as_of=date(2023, 1, 1))
        b = build_events(past, as_of=date(2023, 1, 1))
        a = a[a["t0"] <= pd.Timestamp(cut)].set_index(["company_key", "t0"]).sort_index()
        b = b.set_index(["company_key", "t0"]).sort_index()
        assert len(a) == len(b) > 100
        pd.testing.assert_frame_equal(a[FEATURES], b[FEATURES])


def test_km_matches_labelled_rate_without_censoring():
    ev = build_events(population(n_companies=600, end=date(2015, 12, 31)), as_of=date(2023, 1, 1))
    km = km_repeat_curve(ev, [365], as_of=date(2023, 1, 1))
    raw = (ev["next_gap_days"] <= 365).mean()
    assert abs(km[365] - raw) < 1e-9


def test_load_notices_rolls_up_to_canonical_company(db):
    canon = Company(name="Acme Inc")
    db.add(canon)
    db.flush()
    dupe = Company(name="ACME Incorporated - Plant 2", canonical_company_id=canon.id)
    db.add(dupe)
    db.flush()
    db.add_all([
        Notice(notice_id="a", state="AA", employer="Acme Inc", notice_date=D0,
               company_id=canon.id),
        Notice(notice_id="b", state="AA", employer="ACME Plant 2",
               notice_date=D0 + timedelta(days=90), company_id=dupe.id),
        Notice(notice_id="c", state="AA", employer="The Widget Co.", notice_date=D0),
        Notice(notice_id="d", state="AA", employer="Gone", notice_date=D0, is_superseded=True),
    ])
    db.commit()
    df = load_notices(db).set_index("notice_id")
    assert df.loc["a", "company_key"] == df.loc["b", "company_key"] == f"c{canon.id}"
    assert df.loc["c", "company_key"] == "nwidget"
    assert "d" not in df.index

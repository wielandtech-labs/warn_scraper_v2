"""ER stage A3: merge suggestions, the admin queue, feedback labels, remapped keys."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.er_synthetic import profiles as synthetic_profiles
from warn_v2 import auth
from warn_v2.db.models import Company, CompanyMergeOverride, CompanyMergeSuggestion, Notice, User
from warn_v2.ml.er.remap import er_company_keys
from warn_v2.ml.er.run import Fitted, evaluate, fit_all
from warn_v2.ml.er.suggest import load_feedback, suggestions, write_suggestions

NO_OVERRIDES = pd.DataFrame(columns=["company_id", "target_company_id"])


def _fitted(prof: pd.DataFrame, edges: list[tuple[int, int, float]]) -> Fitted:
    """A Fitted whose pair scores are given directly (no model needed)."""
    pairs = pd.DataFrame([(a, b) for a, b, _ in edges], columns=["a", "b"])
    scores = np.array([s for *_, s in edges], dtype=float)
    return Fitted(prof, pairs, pd.DataFrame(), np.full(len(edges), np.nan), scores,
                  None, np.zeros(len(edges), bool))  # type: ignore[arg-type]


def _prof(ids, canonical, notices, names=None):
    n = len(ids)
    return pd.DataFrame({
        "company_id": ids, "current_canonical_id": canonical, "n_notices": notices,
        "unique_id": [None] * n, "website_domain": [None] * n,
        "canonical": names or [f"c{i}" for i in ids], "name": names or [f"C{i}" for i in ids],
        "enriched": [False] * n, "enrichment_confidence": [None] * n,
    })


# --- suggestions -------------------------------------------------------------

def test_proposes_merging_the_smaller_current_group_into_the_bigger_one():
    # Rows 0,1 are already one group (1 -> 0); row 2 is its own; the model
    # links all three strongly. Row 3 is unrelated.
    prof = _prof([10, 11, 12, 13], [None, 10, None, None], [5, 2, 1, 1])
    f = _fitted(prof, [(0, 1, .99), (0, 2, .95), (1, 2, .93), (2, 3, .1)])
    out = suggestions(f, NO_OVERRIDES)
    assert out[["company_id", "target_company_id"]].values.tolist() == [[12, 10]]
    assert out.loc[0, "score"] == pytest.approx((.95 + .93) / 2)


def test_threshold_decided_pairs_and_keep_separate_overrides_filter_proposals():
    prof = _prof([10, 11], [None, None], [3, 1])
    f = _fitted(prof, [(0, 1, .85)])
    assert len(suggestions(f, NO_OVERRIDES, min_score=0.8)) == 1
    assert suggestions(f, NO_OVERRIDES, min_score=0.9).empty
    assert suggestions(f, NO_OVERRIDES, {frozenset((10, 11))}).empty
    keep_apart = pd.DataFrame({"company_id": [11], "target_company_id": [None]})
    assert suggestions(f, keep_apart).empty


def test_a_group_the_model_split_is_not_proposed():
    # Group {10, 11} (11 -> 10): the model links 11 to 12 but not 10 to 12.
    # Accepting "10 into 12" would move 10 too, so nothing is proposed.
    prof = _prof([10, 11, 12], [None, 10, None], [1, 1, 9])
    f = _fitted(prof, [(1, 2, .99), (0, 1, .1)])
    assert suggestions(f, NO_OVERRIDES).empty


def test_rejected_pairs_stay_apart_even_through_a_third_group():
    # 10 and 11 were rejected; both link strongly to 12, which now has the
    # most notices. Without the rejection both would be proposed into 12.
    prof = _prof([10, 11, 12], [None, None, None], [1, 1, 9])
    edges = [(0, 1, .99), (0, 2, .97), (1, 2, .97)]
    assert len(suggestions(_fitted(prof, edges), NO_OVERRIDES)) == 2
    rejected = {frozenset((10, 11))}
    out = suggestions(_fitted(prof, edges), NO_OVERRIDES, rejected, rejected)
    merged = set(out["company_id"])
    assert not {10, 11} <= merged  # never both into one group
    keys = er_company_keys(_fitted(prof, edges), NO_OVERRIDES, rejected)
    assert keys[10] != keys[11]


def test_no_proposal_inside_one_current_group():
    prof = _prof([10, 11], [None, 10], [3, 1])
    assert suggestions(_fitted(prof, [(0, 1, .99)]), NO_OVERRIDES).empty


def test_write_replaces_the_open_queue_and_never_touches_decided_rows(db):
    a, b, c = (Company(name=n) for n in ("A", "B", "C"))
    db.add_all([a, b, c])
    db.flush()
    db.add(CompanyMergeSuggestion(company_id=c.id, target_company_id=a.id, score=.9,
                                  model_version="v0", status="rejected"))
    db.add(CompanyMergeSuggestion(company_id=b.id, target_company_id=c.id, score=.9,
                                  model_version="v0", status="open"))
    db.commit()
    proposals = pd.DataFrame([(b.id, a.id, .95), (c.id, a.id, .99)],
                             columns=["company_id", "target_company_id", "score"])
    stats = write_suggestions(db, proposals, "v1")
    db.commit()
    assert stats == {"inserted": 1, "updated": 0, "removed": 1, "skipped_decided": 1}
    db.expire_all()
    rows = {(s.company_id, s.target_company_id): s for s in db.query(CompanyMergeSuggestion)}
    assert rows[(c.id, a.id)].status == "rejected" and rows[(c.id, a.id)].model_version == "v0"
    assert rows[(b.id, a.id)].status == "open" and rows[(b.id, a.id)].model_version == "v1"
    assert (b.id, c.id) not in rows  # the model no longer proposes it


# --- admin API ---------------------------------------------------------------

PASSWORD = "correct-horse-battery"


@pytest.fixture()
def api_client(db):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    yield TestClient(app, base_url="https://testserver", raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _login(db, client, role: str) -> User:
    u = User(email=f"{role}@example.com", password_hash=auth.hash_password(PASSWORD), role=role)
    db.add(u)
    db.commit()
    assert client.post("/api/auth/login",
                       json={"email": u.email, "password": PASSWORD}).status_code == 200
    return u


@pytest.fixture()
def queue(db):
    target, src, other = Company(name="Kmart Corporation"), Company(name="KMART #7435"), \
        Company(name="Kmart Cafe")
    db.add_all([target, src, other])
    db.flush()
    for i, (co, st) in enumerate([(target, "FL"), (target, "GA"), (src, "FL"), (other, "TX")]):
        db.add(Notice(notice_id=f"q{i}", state=st, employer=co.name, company_id=co.id))
    s1 = CompanyMergeSuggestion(company_id=src.id, target_company_id=target.id, score=.97,
                                model_version="er-test")
    s2 = CompanyMergeSuggestion(company_id=other.id, target_company_id=target.id, score=.81,
                                model_version="er-test")
    db.add_all([s1, s2])
    db.commit()
    return {"target": target, "src": src, "other": other, "s1": s1, "s2": s2}


def test_suggestion_endpoints_are_admin_only(db, api_client, queue):
    url = "/api/admin/companies/merge-suggestions"
    assert api_client.get(url).status_code == 401
    _login(db, api_client, "paid")
    assert api_client.get(url).status_code == 403
    assert api_client.post(f"{url}/{queue['s1'].id}/accept").status_code == 403
    assert api_client.post(f"{url}/{queue['s1'].id}/reject").status_code == 403


def test_list_shows_groups_strongest_first(db, api_client, queue):
    _login(db, api_client, "admin")
    body = api_client.get("/api/admin/companies/merge-suggestions").json()
    assert [r["id"] for r in body] == [queue["s1"].id, queue["s2"].id]
    first = body[0]
    assert first["company"]["name"] == "KMART #7435" and first["company"]["notices"] == 1
    assert first["target"]["notices"] == 2 and first["target"]["states"] == ["FL", "GA"]
    assert first["company"]["root_id"] == queue["src"].id


def test_accept_withdraws_siblings_and_refuses_stale_suggestions(db, api_client, queue):
    _login(db, api_client, "admin")
    base = "/api/admin/companies/merge-suggestions"
    # A second open suggestion would move the same group elsewhere.
    sib = CompanyMergeSuggestion(company_id=queue["src"].id,
                                 target_company_id=queue["other"].id, score=.8,
                                 model_version="er-test")
    db.add(sib)
    db.commit()
    sib_id = sib.id
    assert api_client.post(f"{base}/{queue['s1'].id}/accept").status_code == 200
    db.expire_all()
    assert db.get(CompanyMergeSuggestion, sib_id) is None

    # "other" is merged by hand meanwhile: its suggestion is stale now.
    db.get(Company, queue["other"].id).canonical_company_id = queue["src"].id
    db.commit()
    resp = api_client.post(f"{base}/{queue['s2'].id}/accept")
    assert resp.status_code == 409 and "Stale" in resp.json()["detail"]


def test_accept_merges_through_an_override_and_reject_writes_none(db, api_client, queue):
    admin = _login(db, api_client, "admin")
    base = "/api/admin/companies/merge-suggestions"
    resp = api_client.post(f"{base}/{queue['s1'].id}/accept")
    assert resp.status_code == 200, resp.text
    assert resp.json()["canonical_id"] == queue["target"].id
    db.expire_all()
    assert db.get(Company, queue["src"].id).canonical_company_id == queue["target"].id
    ov = db.get(CompanyMergeOverride, queue["src"].id)
    assert ov.target_company_id == queue["target"].id and "ER suggestion" in ov.note
    s1 = db.get(CompanyMergeSuggestion, queue["s1"].id)
    assert s1.status == "accepted" and s1.decided_by == admin.id

    resp = api_client.post(f"{base}/{queue['s2'].id}/reject")
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"
    db.expire_all()
    assert db.get(CompanyMergeOverride, queue["other"].id) is None
    assert db.get(Company, queue["other"].id).canonical_company_id is None

    # Decided suggestions can't be decided again.
    assert api_client.post(f"{base}/{queue['s1'].id}/reject").status_code == 409
    assert api_client.post(f"{base}/{queue['s2'].id}/accept").status_code == 409
    assert api_client.post(f"{base}/999999/accept").status_code == 404


# --- feedback as gold, remapped keys --------------------------------------------

def test_decisions_become_feedback_gold_and_are_reported(db):
    prof, _ = synthetic_profiles(n_entities=120)
    ids = prof["company_id"].tolist()
    for cid, name in zip(ids, prof["name"], strict=True):
        db.add(Company(id=int(cid), name=name))
    db.flush()
    db.add_all([
        CompanyMergeSuggestion(company_id=ids[1], target_company_id=ids[0], score=.9,
                               model_version="v", status="accepted"),
        CompanyMergeSuggestion(company_id=ids[3], target_company_id=ids[2], score=.85,
                               model_version="v", status="rejected"),
        CompanyMergeSuggestion(company_id=ids[5], target_company_id=ids[4], score=.95,
                               model_version="v", status="open"),
    ])
    db.commit()
    # The accepted merge has happened: row 1 now sits in row 0's group.
    prof = prof.copy()
    prof.loc[1, "current_canonical_id"] = int(ids[0])
    fb = load_feedback(db, prof)
    assert sorted(map(tuple, fb.to_numpy().tolist())) == [(0, 1, 1), (2, 3, 0)]

    report = evaluate(fit_all(prof), NO_OVERRIDES, None, fb)
    g = report["gold_feedback"]
    assert g["pairs"] == 2 and g["accepted"] == 1
    assert "system" not in g["pairwise"] and "model" in g["pairwise"]


def test_er_keys_follow_the_system_clustering():
    prof = _prof([10, 11, 12], [None, None, None], [1, 1, 1])
    keys = er_company_keys(_fitted(prof, [(0, 1, .99), (1, 2, .05)]), NO_OVERRIDES)
    assert keys == {10: "e10", 11: "e10", 12: "e12"}


def test_load_notices_uses_the_key_map(db):
    from datetime import date

    from warn_v2.ml.events import load_notices

    a, b = Company(name="Alpha"), Company(name="Beta")
    db.add_all([a, b])
    db.flush()
    for i, co in enumerate([a, b]):
        db.add(Notice(notice_id=f"m{i}", state="AA", employer=co.name, company_id=co.id,
                      notice_date=date(2020, 1, 1 + i)))
    db.commit()
    plain = set(load_notices(db)["company_key"])
    assert plain == {f"c{a.id}", f"c{b.id}"}
    merged = set(load_notices(db, key_map={a.id: "e1", b.id: "e1"})["company_key"])
    assert merged == {"e1"}


def test_suggest_cli_dry_run_writes_nothing_then_fills_the_queue(db):
    from click.testing import CliRunner

    from tests.test_ml_er import _seed_db
    from warn_v2.cli import main

    _seed_db(db)
    before = {c.id: c.canonical_company_id for c in db.query(Company)}
    res = CliRunner().invoke(main, ["ml-er-suggest", "--dry-run", "--min-score", "0.5"])
    assert res.exit_code == 0, res.output
    assert db.query(CompanyMergeSuggestion).count() == 0

    res = CliRunner().invoke(main, ["ml-er-suggest", "--min-score", "0.5"])
    assert res.exit_code == 0, res.output
    db.expire_all()
    rows = db.query(CompanyMergeSuggestion).all()
    # Synthetic variants the name heuristics miss are proposed...
    assert rows and all(r.status == "open" and r.score >= 0.5 for r in rows)
    # ...and nothing about the companies themselves changed.
    assert {c.id: c.canonical_company_id for c in db.query(Company)} == before

"""Routes: /admin — admin-only data curation (company merge/unmerge, and the
entity-resolution model's merge suggestions)."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db, require_admin
from warn_v2.companies.merge import apply_overrides, flatten
from warn_v2.db.models import (
    Company,
    CompanyMergeOverride,
    CompanyMergeSuggestion,
    Notice,
    User,
)
from warn_v2.scripts.consolidate_companies import _parent_group_key

router = APIRouter(prefix="/admin", tags=["admin"])


class MergeRequest(BaseModel):
    target_id: int
    source_ids: list[int] = Field(min_length=1, max_length=500)
    note: str | None = Field(None, max_length=1000)


class MergeResult(BaseModel):
    canonical_id: int  # the group's root after the change (the display label row)
    updated: int  # company rows whose canonical pointer changed


def _upsert_override(
    db: Session, company_id: int, target_id: int | None, admin: User, note: str | None
) -> None:
    row = db.get(CompanyMergeOverride, company_id)
    if row is None:
        row = CompanyMergeOverride(company_id=company_id)
        db.add(row)
    row.target_company_id = target_id
    row.decided_by = admin.id
    row.decided_at = datetime.now(UTC)
    row.note = note


def _reconcile(db: Session) -> tuple[dict[int, int], int]:
    """Re-resolve the stored merge map with every override applied.

    Same apply_overrides + flatten the nightly consolidator runs, so the
    immediate result and the next recompute agree. Starting from the stored
    (already flat) pointers is idempotent for overrides applied earlier.
    """
    db.flush()
    current: dict[int, int] = dict(
        db.execute(
            select(Company.id, Company.canonical_company_id).where(
                Company.canonical_company_id.is_not(None)
            )
        ).all()
    )
    overrides = db.execute(
        select(CompanyMergeOverride.company_id, CompanyMergeOverride.target_company_id)
        .order_by(CompanyMergeOverride.decided_at.desc())
    ).all()
    new = flatten(apply_overrides(current, overrides))

    changed = [cid for cid in current.keys() | new.keys() if current.get(cid) != new.get(cid)]
    rows = db.scalars(select(Company).where(Company.id.in_(changed))) if changed else []
    for c in rows:
        c.canonical_company_id = new.get(c.id)
        if c.canonical_company_id is None:
            c.parent_group_key = _parent_group_key(c)  # newly canonical: needs a key
    db.commit()
    return new, len(changed)


@router.post("/companies/merge", response_model=MergeResult)
def merge_companies(
    body: MergeRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MergeResult:
    """Merge ``source_ids`` into ``target_id``'s group; the target's name labels it."""
    source_ids = set(body.source_ids)
    if body.target_id in source_ids:
        raise HTTPException(status_code=400, detail="target_id must not be in source_ids")
    wanted = source_ids | {body.target_id}
    found = set(db.scalars(select(Company.id).where(Company.id.in_(wanted))))
    if missing := sorted(wanted - found):
        raise HTTPException(status_code=404, detail=f"Unknown company ids: {missing}")

    for sid in source_ids:
        _upsert_override(db, sid, body.target_id, admin, body.note)
    new, updated = _reconcile(db)
    return MergeResult(canonical_id=new.get(body.target_id, body.target_id), updated=updated)


@router.post("/companies/{company_id}/unmerge", response_model=MergeResult)
def unmerge_company(
    company_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MergeResult:
    """Keep ``company_id`` separate, overriding any automatic or manual merge."""
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")
    _upsert_override(db, company_id, None, admin, None)
    _, updated = _reconcile(db)
    return MergeResult(canonical_id=company_id, updated=updated)


# --- entity-resolution merge suggestions --------------------------------------
# Written by `warn-v2 ml-er-suggest` (warn_v2/ml/er/suggest.py). Accepting one
# is an ordinary admin merge (an override); rejecting records the decision only
# (a keep-separate override would also undo the company's other merges). Every
# decision is also a gold label for the next `ml-er-eval`.


class SuggestionSide(BaseModel):
    id: int
    name: str
    root_id: int  # the company's current group; != id once it was merged elsewhere
    notices: int  # live notices across that group
    states: list[str]


class SuggestionOut(BaseModel):
    id: int
    company: SuggestionSide  # merged into ...
    target: SuggestionSide  # ... this one's group
    score: float
    model_version: str
    status: str
    created_at: datetime


class SuggestionDecision(BaseModel):
    id: int
    status: str


def _sides(db: Session, ids: set[int]) -> dict[int, SuggestionSide]:
    """Name, current group root, live notice count and states per company."""
    if not ids:
        return {}
    info = {i: (n, c or i) for i, n, c in db.execute(
        select(Company.id, Company.name, Company.canonical_company_id)
        .where(Company.id.in_(ids))).all()}
    roots = {r for _, r in info.values()}
    group = func.coalesce(Company.canonical_company_id, Company.id)
    counts: dict[int, int] = defaultdict(int)
    states: dict[int, set[str]] = defaultdict(set)
    # One grouped scan: rows of every root's group, by state.
    for r, st, n in db.execute(
        select(group, Notice.state, func.count(Notice.notice_id))
        .join(Notice, Notice.company_id == Company.id)
        .where(Company.id.in_(select(Company.id).where(group.in_(roots))),
               Notice.is_superseded.is_(False))
        .group_by(group, Notice.state)
    ).all():
        counts[int(r)] += int(n)
        states[int(r)].add(st)
    out = {}
    for i in ids:
        name, root = info.get(i, (f"#{i}", i))
        out[i] = SuggestionSide(id=i, name=name, root_id=root, notices=counts.get(root, 0),
                                states=sorted(states.get(root, set())))
    return out


@router.get("/companies/merge-suggestions", response_model=list[SuggestionOut])
def list_merge_suggestions(
    status: Literal["open", "accepted", "rejected"] = "open",
    limit: int = Query(200, ge=1, le=500),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SuggestionOut]:
    """The model's proposed merges, strongest first."""
    rows = db.scalars(
        select(CompanyMergeSuggestion).where(CompanyMergeSuggestion.status == status)
        .order_by(CompanyMergeSuggestion.score.desc(), CompanyMergeSuggestion.id)
        .limit(limit)
    ).all()
    sides = _sides(db, {r.company_id for r in rows} | {r.target_company_id for r in rows})
    return [
        SuggestionOut(id=r.id, company=sides[r.company_id], target=sides[r.target_company_id],
                      score=r.score, model_version=r.model_version, status=r.status,
                      created_at=r.created_at)
        for r in rows
    ]


def _open_suggestion(db: Session, suggestion_id: int) -> CompanyMergeSuggestion:
    # Row lock (Postgres): two admins deciding the same suggestion serialize,
    # and the second sees it decided.
    row = db.scalars(
        select(CompanyMergeSuggestion).where(CompanyMergeSuggestion.id == suggestion_id)
        .with_for_update()
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if row.status != "open":
        raise HTTPException(status_code=409, detail=f"Suggestion already {row.status}")
    return row


@router.post("/companies/merge-suggestions/{suggestion_id}/accept", response_model=MergeResult)
def accept_merge_suggestion(
    suggestion_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> MergeResult:
    """Merge the suggested company into the target's group, as a manual merge would.

    Only while the company is still the root of its group, as it was when the
    model proposed it: otherwise its override would now move a different
    group (or undo another merge), so the suggestion is stale (409) until the
    next ml-er-suggest run. Accepting also withdraws the company's other open
    suggestions, which proposed moving the same group elsewhere."""
    row = _open_suggestion(db, suggestion_id)
    company = db.get(Company, row.company_id)
    if company is None or company.canonical_company_id is not None:
        raise HTTPException(status_code=409,
                            detail="Stale suggestion: the company was merged since it was made")
    row.status, row.decided_by, row.decided_at = "accepted", admin.id, datetime.now(UTC)
    db.execute(
        delete(CompanyMergeSuggestion).where(
            CompanyMergeSuggestion.company_id == row.company_id,
            CompanyMergeSuggestion.status == "open",
            CompanyMergeSuggestion.id != row.id,
        )
    )
    _upsert_override(
        db, row.company_id, row.target_company_id, admin,
        f"ER suggestion #{row.id} (score {row.score:.2f}, {row.model_version})",
    )
    new, updated = _reconcile(db)  # commits the decision with the merge
    return MergeResult(canonical_id=new.get(row.target_company_id, row.target_company_id),
                       updated=updated)


@router.post("/companies/merge-suggestions/{suggestion_id}/reject",
             response_model=SuggestionDecision)
def reject_merge_suggestion(
    suggestion_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SuggestionDecision:
    """Record that these are different companies. Nothing else changes."""
    row = _open_suggestion(db, suggestion_id)
    row.status, row.decided_by, row.decided_at = "rejected", admin.id, datetime.now(UTC)
    db.commit()
    return SuggestionDecision(id=row.id, status=row.status)

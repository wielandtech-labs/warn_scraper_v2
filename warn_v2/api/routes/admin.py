"""Routes: /admin — admin-only data curation (company merge/unmerge)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db, require_admin
from warn_v2.companies.merge import apply_overrides, flatten
from warn_v2.db.models import Company, CompanyMergeOverride, User
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

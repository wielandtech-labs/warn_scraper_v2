"""Model-level invariants that a refactor could silently break."""
from __future__ import annotations

import pytest

from warn_v2.db.models import Company


@pytest.mark.parametrize(
    ("attribute", "column"),
    [
        ("unique_id", "duns"),
        ("parent_unique_id", "parent_duns"),
        ("global_ultimate_unique_id", "global_ultimate_duns"),
    ],
)
def test_unique_id_attrs_keep_their_original_column_names(
    attribute: str, column: str
) -> None:
    """The *_unique_id rename was terminology-only — the DB was never touched.

    Dropping the explicit column name from ``mapped_column`` would make
    SQLAlchemy derive it from the attribute instead, so every query would hit a
    column that does not exist in prod. No migration renames these.
    """
    assert getattr(Company, attribute).property.columns[0].name == column
    assert column in Company.__table__.c

"""Tests for conservative company-name normalization."""
from __future__ import annotations

from warn_v2.companies.normalize import canonical_name


def test_legal_form_variants_collapse():
    keys = {
        canonical_name("Acme Inc"),
        canonical_name("Acme, LLC"),
        canonical_name("ACME"),
        canonical_name("Acme Inc."),
        canonical_name("Acme Co."),
    }
    assert keys == {"acme"}


def test_descriptive_words_preserved_no_over_merge():
    # These are DIFFERENT companies — must not collapse.
    assert canonical_name("Smith Services") != canonical_name("Smith Technologies")
    assert canonical_name("Smith Services") == "smith services"
    assert canonical_name("Acme Holdings") == "acme holdings"  # 'holdings' kept


def test_multiple_trailing_legal_tokens_stripped():
    assert canonical_name("Widgets Co Inc") == "widgets"


def test_punctuation_and_whitespace():
    assert canonical_name("  Foo  &  Bar,  Inc.  ") == "foo bar"


def test_all_legal_tokens_falls_back():
    # Degenerate name made only of legal tokens — keep something rather than "".
    assert canonical_name("LLC") == "llc"


def test_empty_and_none():
    assert canonical_name("") == ""
    assert canonical_name(None) == ""

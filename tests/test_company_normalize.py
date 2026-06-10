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


def test_leading_store_number_prefix_stripped():
    # Branches of one org distinguished only by a (NNNN) location code collapse.
    keys = {
        canonical_name("(1045) San Diego LGBT Community Center"),
        canonical_name("(1640) San Diego LGBT Community Center"),
        canonical_name("(3636) San Diego LGBT Community Center"),
    }
    assert keys == {"san diego lgbt community center"}


def test_hash_store_number_stripped():
    assert canonical_name("Food 4 Less #364") == canonical_name("Food 4 Less #12")
    assert canonical_name("Food 4 Less #364") == "food 4 less"


def test_leading_number_without_parens_is_kept():
    # "24" is part of the name, not a store code — must not be stripped.
    assert canonical_name("24 Hour Fitness USA Inc.") == "24 hour fitness usa"


def test_empty_and_none():
    assert canonical_name("") == ""
    assert canonical_name(None) == ""

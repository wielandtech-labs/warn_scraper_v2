"""Tests for conservative company-name normalization."""
from __future__ import annotations

from warn_v2.companies.normalize import (
    canonical_name,
    is_unsearchable,
    match_is_consistent,
    search_name,
)


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


# ---------------------------------------------------------------------------
# search_name — external-search query cleaning (case-preserving)
# ---------------------------------------------------------------------------

def test_search_name_strips_dash_site_segments():
    assert search_name("Google - Bordeaux") == "Google"
    assert search_name("Google - 242") == "Google"
    assert search_name("Amazon - SNA 20") == "Amazon"


def test_search_name_strips_trailing_site_numbers():
    assert search_name("MV Transportation 4499") == "MV Transportation"
    assert search_name("10x Genomics, Inc. (6230)") == "10x Genomics, Inc."


def test_search_name_strips_store_markers():
    assert search_name("(1045) San Diego LGBT Community Center") == (
        "San Diego LGBT Community Center"
    )
    assert search_name("Food 4 Less #364") == "Food 4 Less"


def test_search_name_keeps_real_names_intact():
    assert search_name("Mercedes-Benz USA") == "Mercedes-Benz USA"  # hyphen, not dash segment
    assert search_name("Jo-Ann Stores Support Center, Inc.") == (
        "Jo-Ann Stores Support Center, Inc."
    )
    assert search_name("24 Hour Fitness USA Inc.") == "24 Hour Fitness USA Inc."
    # dash segment with its own legal form is a real entity, not a site tag
    assert search_name("Acme - Widgets LLC") == "Acme - Widgets LLC"
    assert search_name("Manna Beverages MBV-CA LLC 6725") == "Manna Beverages MBV-CA LLC"


def test_search_name_degenerate_inputs():
    assert search_name("") == ""
    assert search_name(None) == ""
    assert search_name("4499") == "4499"  # nothing left after strip -> original


# ---------------------------------------------------------------------------
# search_name — aggressive cleaning, driven by real WARN names that previously
# fell through to claude/edgar without a DUNS (see PR notes).
# ---------------------------------------------------------------------------

def test_search_name_strips_trailing_parentheticals():
    # Any trailing (...) — not just numeric — is a site/branch designator.
    assert search_name("Epic Games Inc. (Remote Employees in Los Angeles)") == (
        "Epic Games Inc."
    )
    assert search_name("Chevron (N. FM 1788)") == "Chevron"
    assert search_name("ABM Texas (TCC South)") == "ABM Texas"
    assert search_name("Right at School, LLC (KI Jones Elementary)") == "Right at School, LLC"
    assert search_name("Cushman & Wakefield (1000)") == "Cushman & Wakefield"
    assert search_name("Blue Shield of California (San Diego)") == "Blue Shield of California"


def test_search_name_strips_dba_clause():
    assert search_name("Good Sports Plus Ltd. dba Arc") == "Good Sports Plus Ltd."
    assert search_name("GMRI, Inc. d/b/a Eddie V's") == "GMRI, Inc."
    assert search_name("Sapango Inc., dba Tre Posti") == "Sapango Inc."


def test_search_name_strips_descriptive_clause():
    assert search_name("TC&Js Enterprises, franchise operator of Chick-fil-A") == (
        "TC&Js Enterprises"
    )
    # A plain ", Inc." clause must NOT be cut.
    assert search_name("McDonald's Restaurants of California, Inc.") == (
        "McDonald's Restaurants of California, Inc."
    )


def test_search_name_decodes_html_entities():
    assert search_name("McDonald&rsquo;s Restaurants of California, Inc.") == (
        "McDonald's Restaurants of California, Inc."
    )
    assert search_name("Ben &amp; Jerry's") == "Ben & Jerry's"


def test_search_name_strips_appended_address():
    assert search_name("Peraton 1875 Explorer St Reston, VA 20190") == "Peraton"
    assert search_name("Nitto, Inc 809 Principal Ct Chesapeake, VA 23320") == "Nitto, Inc"


def test_search_name_strips_wide_dash_segments():
    assert search_name("Blue Shield of California - Oakland") == "Blue Shield of California"
    assert search_name("Crothall Healthcare - Lakewood Regional Medical Center") == (
        "Crothall Healthcare"
    )
    assert search_name("Scout Distribution, LLC - San Diego") == "Scout Distribution, LLC"
    assert search_name("PULAU Corporation - GMDT") == "PULAU Corporation"


def test_search_name_collapses_multiple_entities():
    assert search_name(
        "10 Roads Express LLC, 10 Roads Service, LLC, 10 Roads Logistics, LLC"
    ) == "10 Roads Express LLC"


def test_search_name_repeated_stem_without_comma_is_kept():
    # Prose repetition is NOT a comma-delimited entity list — leave it alone.
    assert search_name("Los Angeles County of Los Angeles") == (
        "Los Angeles County of Los Angeles"
    )
    assert search_name("New York New York Hotel") == "New York New York Hotel"


def test_search_name_strips_facility_suffix():
    assert search_name("Home Depot Design Center") == "Home Depot"
    assert search_name("Target Corp. Distribution Center") == "Target Corp."


def test_search_name_keeps_facility_like_real_names():
    # "X Logistics/Data/Service Center" can be the company's real name — keep it.
    assert search_name("5 Star Logistics Center") == "5 Star Logistics Center"
    assert search_name("Acme Data Center") == "Acme Data Center"


def test_search_name_collapses_embedded_newlines():
    # Multi-line stored names would otherwise defeat every trailing-anchored
    # rule (".*$" can't cross a "\n"), leaving the clause un-stripped.
    assert search_name(
        "Hollywood Palladium, a subsidiary of Live Nation\nEntertainment, Inc."
    ) == "Hollywood Palladium"
    assert search_name(
        "Advance Stores Company, Incorporated and its subsidiary,\nGolden State Supply LLC"
    ) == "Advance Stores Company, Incorporated"


def test_search_name_strips_and_its_subsidiary_clause():
    assert search_name(
        "Advance Stores Company, Incorporated and its subsidiary, Golden State Supply LLC"
    ) == "Advance Stores Company, Incorporated"
    assert search_name("Acme Corp and its subsidiaries") == "Acme Corp"


def test_search_name_strips_trailing_star_annotation():
    # Footnote/status tails glued to a paren, or introduced by a spaced asterisk.
    assert search_name("Health Net, Inc. (CANCELLED)**") == "Health Net, Inc."
    assert search_name(
        "Bloomin' Brands (Outback Steakhouse) *Due to COVID-19 Tampa, FL 33607"
    ) == "Bloomin' Brands"
    assert search_name(
        "Busch Gardens Williamsburg *Due to COVID-19 Williamsburg, VA 23185"
    ) == "Busch Gardens Williamsburg"


def test_search_name_preserves_mid_name_star():
    # A "*" without leading whitespace is part of the name, not an annotation.
    assert search_name("E*Trade Financial") == "E*Trade Financial"


def test_search_name_strips_unbalanced_open_paren():
    assert search_name("Tyson Foods, Inc. (Amarillo B-Shift Operations") == (
        "Tyson Foods, Inc."
    )


def test_search_name_long_input_is_safe():
    # Guard against ReDoS in the address regex: a digit-prefixed name with no
    # real ZIP must return promptly, not backtrack catastrophically.
    pathological = "Acme 12 " + ("a" * 6000)
    assert isinstance(search_name(pathological), str)


def test_is_unsearchable_flags_lone_generic_token():
    # The dangerous over-strip: distinguishing info was only in the parens.
    assert is_unsearchable(search_name("Alliance (Piera Barbaglia Shaheen Health)"))
    assert is_unsearchable(search_name("Alliance (Virgil Roberts)"))
    assert is_unsearchable("Services")
    # Strong, unique single tokens are still searchable.
    assert not is_unsearchable(search_name("Chevron (N. FM 1788)"))
    assert not is_unsearchable("Peraton")
    assert not is_unsearchable("GI Alliance Management, LLC")


def test_match_is_consistent_guard():
    # Faithful matches: share a DISTINCTIVE token with the original.
    assert match_is_consistent("Epic Games Inc. (Remote Employees)", "Epic Games, Inc.")
    assert match_is_consistent("Chevron (N. FM 1788)", "Chevron Corporation")
    assert match_is_consistent("Peraton 1875 Explorer St Reston, VA", "Peraton Inc")
    assert match_is_consistent("Crothall Healthcare", "Crothall Healthcare Services")
    # Unfaithful: an over-strip resolved to an unrelated company → reject the DUNS.
    assert not match_is_consistent("Peraton 1875 Explorer St", "Booz Allen Hamilton")
    assert not match_is_consistent("Midwest Perishables Inc.", "Acme Corporation")


def test_match_is_consistent_rejects_generic_only_overlap():
    # A shared INDUSTRY word between two different firms is not the same company.
    assert not match_is_consistent("Acme Healthcare", "Sutter Healthcare")
    assert not match_is_consistent("Midwest Logistics", "Eastern Logistics")
    assert not match_is_consistent("Premier Staffing", "National Staffing Solutions")


def test_match_is_consistent_trusts_provider_for_tokenless_names():
    # Ampersand/short names reduce to no significant tokens; auto-rejecting would
    # lock them out of a DUNS forever, so trust the provider's match instead.
    assert match_is_consistent("AT&T", "AT&T Inc")
    assert match_is_consistent("H&M", "H&M Inc")

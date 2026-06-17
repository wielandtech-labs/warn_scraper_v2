"""US state/territory code → display name.

The canonical set of jurisdictions the app exposes as browsable state pages and
in the sitemap. Mirrors the frontend ``US_STATES`` list (50 states + DC) so the
SEO/state-page surface and the filter dropdown stay in lock-step. Kept separate
from the scraper registry so SEO/sitemap generation doesn't import every state
scraper (some pull in Playwright) at request time.
"""
from __future__ import annotations

STATE_NAMES: dict[str, str] = {
    "AK": "Alaska",
    "AL": "Alabama",
    "AR": "Arkansas",
    "AZ": "Arizona",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DC": "District of Columbia",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "IA": "Iowa",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "MA": "Massachusetts",
    "MD": "Maryland",
    "ME": "Maine",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MO": "Missouri",
    "MS": "Mississippi",
    "MT": "Montana",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "NE": "Nebraska",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NV": "Nevada",
    "NY": "New York",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VA": "Virginia",
    "VT": "Vermont",
    "WA": "Washington",
    "WI": "Wisconsin",
    "WV": "West Virginia",
    "WY": "Wyoming",
}


def state_name(code: str | None) -> str | None:
    """Return the display name for a 2-letter code (case-insensitive), or None."""
    if not code:
        return None
    return STATE_NAMES.get(code.upper())


def is_valid_state(code: str | None) -> bool:
    """True if ``code`` is one of the jurisdictions we expose."""
    return state_name(code) is not None

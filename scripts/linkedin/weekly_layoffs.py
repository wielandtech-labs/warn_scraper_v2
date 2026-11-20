#!/usr/bin/env python3
"""Weekly WARN Index data for the LinkedIn draft task.

Fetches the last 7 days of WARN layoff data from the public warnindex.com API
and prints a JSON summary matching the schema the weekly-linkedin-layoffs-draft
skill expects.

Uses only stdlib — no pip installs needed.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

API = "https://warnindex.com/api"

NAICS_SECTOR_RANGES: list[tuple[str, str, str]] = [
    ("11", "11", "Agriculture, Forestry, Fishing and Hunting"),
    ("21", "21", "Mining, Quarrying, and Oil and Gas Extraction"),
    ("22", "22", "Utilities"),
    ("23", "23", "Construction"),
    ("31", "33", "Manufacturing"),
    ("42", "42", "Wholesale Trade"),
    ("44", "45", "Retail Trade"),
    ("48", "49", "Transportation and Warehousing"),
    ("51", "51", "Information"),
    ("52", "52", "Finance and Insurance"),
    ("53", "53", "Real Estate and Rental and Leasing"),
    ("54", "54", "Professional, Scientific, and Technical Services"),
    ("55", "55", "Management of Companies and Enterprises"),
    ("56", "56", "Administrative and Support and Waste Management and Remediation Services"),
    ("61", "61", "Educational Services"),
    ("62", "62", "Health Care and Social Assistance"),
    ("71", "71", "Arts, Entertainment, and Recreation"),
    ("72", "72", "Accommodation and Food Services"),
    ("81", "81", "Other Services (except Public Administration)"),
    ("92", "92", "Public Administration"),
]


def _sector_name(naics_code: str | None) -> str | None:
    if not naics_code or len(naics_code) < 2:
        return None
    prefix = naics_code[:2]
    for lo, hi, name in NAICS_SECTOR_RANGES:
        if lo <= prefix <= hi:
            return name
    return None


def _fetch(path: str) -> object:
    url = f"{API}{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _fetch_all_notices(after: str, before: str) -> list[dict]:
    """Paginate through all notices in the date window, sorted by layoff_count."""
    all_items: list[dict] = []
    offset = 0
    limit = 100
    while True:
        data = _fetch(
            f"/notices?after={after}&before={before}"
            f"&sort_by=layoff_count&sort_dir=desc&limit={limit}&offset={offset}"
        )
        items = data.get("items", [])
        all_items.extend(items)
        if len(items) < limit or len(all_items) >= data.get("total", 0):
            break
        offset += limit
    return all_items


def main() -> None:
    today = datetime.now(timezone.utc).date()
    week_ago = today - timedelta(days=7)
    after = week_ago.isoformat()
    before = (today - timedelta(days=1)).isoformat()

    state_data: list[dict] = _fetch(f"/stats/by-state?after={after}&before={before}")
    industry_data: list[dict] = _fetch(f"/stats/industries?after={after}&before={before}")
    items = _fetch_all_notices(after, before)

    total_notices = sum(s["notice_count"] for s in state_data)
    total_workers = sum(s["layoff_total"] for s in state_data)
    states_with_notices = len(state_data)

    workers_by_state = sorted(
        [{"state": s["state"], "workers": s["layoff_total"]} for s in state_data],
        key=lambda x: x["workers"],
        reverse=True,
    )

    workers_by_sector = sorted(
        [{"sector": s["name"], "workers": s["layoff_total"]} for s in industry_data],
        key=lambda x: x["workers"],
        reverse=True,
    )
    workers_with_industry = sum(s["layoff_total"] for s in industry_data)
    workers_unknown = max(0, total_workers - workers_with_industry)
    share_with_industry = (
        round(workers_with_industry / total_workers, 3) if total_workers > 0 else 0
    )

    top_notices = []
    for n in items[:20]:
        company = n.get("company") or {}
        location = n.get("location") or {}
        naics = company.get("naics_code")
        top_notices.append(
            {
                "employer": n.get("employer", ""),
                "workers": n.get("layoff_count") or 0,
                "state": n.get("state", ""),
                "city": location.get("city"),
                "county": location.get("county"),
                "multiple_sites": False,
                "industry": company.get("naics_desc"),
                "sector": _sector_name(naics),
                "type": n.get("closure_category") or n.get("closure_type") or "WARN",
                "notice_date": n.get("notice_date"),
                "effective_date": n.get("effective_date"),
                "url": f"https://warnindex.com/notice/{n['notice_id']}",
            }
        )

    city_totals: dict[tuple[str, str], int] = {}
    for n in items:
        loc = n.get("location") or {}
        city = loc.get("city")
        st = loc.get("state") or n.get("state", "")
        if city:
            key = (city, st)
            city_totals[key] = city_totals.get(key, 0) + (n.get("layoff_count") or 0)
    workers_by_city = sorted(
        [{"city": k[0], "state": k[1], "workers": v} for k, v in city_totals.items()],
        key=lambda x: x["workers"],
        reverse=True,
    )[:20]

    result = {
        "week_start": after,
        "week_end": before,
        "notices": total_notices,
        "workers": total_workers,
        "states_with_notices": states_with_notices,
        "top_notices": top_notices,
        "workers_by_state": workers_by_state,
        "workers_by_city": workers_by_city,
        "workers_by_sector": workers_by_sector,
        "workers_unknown_industry": workers_unknown,
        "share_workers_with_industry": share_with_industry,
    }

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()

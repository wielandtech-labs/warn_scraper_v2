"""Oklahoma WARN scraper.

Source: https://www.employoklahoma.gov/Participants/s/warnnotices
Data:   Salesforce Experience Cloud (OESC's "Employ Oklahoma" portal, which
        replaced okjobmatch.com in May 2026). The page is a Lightning app, but
        its data comes from a guest-accessible Aura Apex action:

  POST /Participants/s/sfsites/aura?r=1&aura.ApexAction.execute=1
    message      = {"actions":[{"descriptor":
                   "aura://ApexActionController/ACTION$execute", "params":
                   {"classname":"OESC_JS_getWARNLayoffNotices",
                    "method":"getListofLayoffAccService", ...}}]}
    aura.context = {"mode":"PROD","fwuid":<from shell page, tolerates null>,...}
    aura.token   = "null"   (guest — no csrf token required)

The action returns every WARN record since 2001 in one JSON payload. Records
carry employer, notice date, closure type, and usually city/zip/workforce
board; there is no employee-count field.

Gotcha: only the ``www.`` host serves guests — the bare host 302s to a login
page.
"""
from __future__ import annotations

import json
import re

import httpx

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_HOST = "https://www.employoklahoma.gov"
_SOURCE_URL = f"{_HOST}/Participants/s/warnnotices"
_AURA_URL = f"{_HOST}/Participants/s/sfsites/aura?r=1&aura.ApexAction.execute=1"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": _SOURCE_URL,
}

# fwuid appears plain in inline scripts and URL-encoded in script srcs.
_FWUID_RE = re.compile(r'"fwuid":"([^"]+)"|fwuid%22%3A%22([^%"]+)%22')

_MESSAGE = json.dumps(
    {
        "actions": [
            {
                "id": "1;a",
                "descriptor": "aura://ApexActionController/ACTION$execute",
                "callingDescriptor": "UNKNOWN",
                "params": {
                    "namespace": "",
                    "classname": "OESC_JS_getWARNLayoffNotices",
                    "method": "getListofLayoffAccService",
                    "cacheable": False,
                    "isContinuation": False,
                },
            }
        ]
    }
)


def _norm_zip(value: str | None) -> str | None:
    s = as_str(value)
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return digits[:5] if len(digits) >= 5 else None


class OKScraper:
    state = "OK"
    source_url = _SOURCE_URL
    expected_row_range = (100, 2_000)  # cumulative since 2001; 217 in Jul 2026
    required_fields = frozenset({"employer", "notice_date"})
    # raw_notice_url is never set — the portal has no per-notice page.
    raw_notice_url_is_pdf = False

    def fetch(self) -> bytes:
        try:
            with httpx.Client(headers=_UA, follow_redirects=True, timeout=60) as client:
                shell = client.get(_SOURCE_URL)
                shell.raise_for_status()
                m = _FWUID_RE.search(shell.text)
                fwuid = (m.group(1) or m.group(2)) if m else None
                context = {
                    "mode": "PROD",
                    "fwuid": fwuid,
                    "app": "siteforce:communityApp",
                    "loaded": {},
                    "dn": [],
                    "globals": {},
                    "uad": True,
                }
                r = client.post(
                    _AURA_URL,
                    data={
                        "message": _MESSAGE,
                        "aura.context": json.dumps(context),
                        "aura.pageURI": "/Participants/s/warnnotices",
                        "aura.token": "null",
                    },
                )
                r.raise_for_status()
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"OK: Aura request error: {e}") from e

        # Classify framework-level errors (stale fwuid, exceptions) as fetch
        # failures so a transient Aura hiccup doesn't look like a parser bug.
        try:
            action = json.loads(r.content)["actions"][0]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as e:
            raise ScrapeFailed(f"OK: unexpected Aura response shape: {e}") from e
        if action.get("state") != "SUCCESS":
            raise ScrapeFailed(f"OK: Aura action state={action.get('state')!r}")
        return r.content

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ParseFailed(f"OK: JSON decode error: {e}") from e

        try:
            records = data["actions"][0]["returnValue"]["returnValue"]
        except (KeyError, IndexError, TypeError) as e:
            raise ParseFailed(f"OK: Aura payload missing record list: {e}") from e
        if not records:
            raise ParseFailed("OK: Aura action returned no records")

        rows: list[NoticeRow] = []
        for rec in records:
            employer = as_str(rec.get("OESC_Employer_Name__c"))
            if not employer:
                continue
            notice_date = as_date(rec.get("Launchpad__Notice_Date__c"))
            if notice_date is None:
                continue
            board = as_str(rec.get("Select_Local_Workforce_Board__c"))
            rows.append(
                NoticeRow(
                    state="OK",
                    employer=employer,
                    notice_date=notice_date,
                    closure_type=as_str(rec.get("Launchpad__Layoff_Closure_Type__c")),
                    city=as_str(rec.get("OESC_Employer_City__c")),
                    zip=_norm_zip(rec.get("OESC_Employer_Zip_Code__c")),
                    source_url=_SOURCE_URL,
                    extra={"local_workforce_board": board} if board else {},
                )
            )
        return rows


register(OKScraper())

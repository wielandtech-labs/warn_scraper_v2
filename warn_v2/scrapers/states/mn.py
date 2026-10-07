"""Minnesota WARN scraper.

Live source: the "Minnesota WARN Notices" list on DEED's Layoff Resources page —
one entry per WARN notice received ("<a href=notice.pdf>Employer</a> - M/D/YYYY").
The page is Radware bot-protected: plain httpx (and headless browsers) get a 302
to a validate.perfdrive.com challenge, but curl_cffi with ``impersonate="chrome"``
receives the real page (verified 2026-10-07). The list carries no worker count or
city — those live only in the free-form notice letters.

Until 2026-10 the live scrape read DEED's monthly "Plant Closings/Mass
Layoffs/WARN Report" PDFs (discovered via Wayback CDX) and kept the WARN Act=YES
rows. That source silently went stale: Wayback stopped capturing new monthlies
after June 2026, the June report's new layout ("Yes", a "WAR / N Act" header)
parsed to 0 rows, and the monthlies only list notices the Rapid Response Team
worked on — Jan-Apr 2026 had 3 WARN=YES rows against 10 notices on the WARN
list. The monthly-PDF parsers below remain for the historical backfill
(``backfill-historical --state MN``).

Monthly PDF format changed between 2025 and 2026:
  2025: wide merged-cell table; text extraction used for parsing.
  2026: clean 10-column table; pdfplumber.extract_table() works.
Both formats are detected automatically.

Schema (2026 clean format confirmed, May 2026):
  Layoff Name | Account: City | Account: Industry | Layoff Start |
  WARN Act | WARN Received | Layoff Type | Layoff Status | Federal Impact | Affected Workers

Historical backfill covers the 2015-2024 archive eras (monthlies 2015-16 and
2022-24, annual summaries 2018-2021) via a word-position parser that derives
column bounds from the header words — see _parse_archive_words. The 2022-2024
year-end cumulative roll-ups are skipped in discovery: they re-list every
monthly filing with glued employer cells and doubled counts (see
_drop_cumulative_reports).
"""
from __future__ import annotations

import calendar
import io
import logging
import re
from bisect import bisect_right
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import RequestException

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

log = logging.getLogger(__name__)

_PAGE_URL = "https://mn.gov/deed/business/layoff-resources/"
_BASE_URL = "https://mn.gov"
_CDX_API = "http://web.archive.org/cdx/search/cdx"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Wayback CDX returns transient 503s under load (seen repeatedly 2026-07-08);
# a single failure otherwise aborts discovery → 0 rows. Retry with backoff.
_CDX_BACKOFFS = (5, 20, 60)


def _cdx_query(params: dict) -> list:
    """Query the Wayback CDX API with retry/backoff; returns the parsed rows."""
    import time

    last: Exception | None = None
    for backoff in (*_CDX_BACKOFFS, None):
        try:
            r = httpx.get(_CDX_API, params=params, headers=_UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            if backoff is None:
                break
            time.sleep(backoff)
    raise ScrapeFailed(f"MN: CDX API error after retries: {last}")

# Regex: match line where a date is followed immediately by YES (= WARN Act YES)
# Captures: [employer-city-industry prefix] [layoff_start_date] [warn_received date|"-"] [rest]
# WARN Received in 2025 PDFs uses M/D (no year) — full date or M/D or dash accepted.
_DATE_PAT = r"\d{1,2}/\d{1,2}/\d{2,4}"
_DATE_ANY = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"  # M/D or M/D/YY or M/D/YYYY
_WARN_YES_RE = re.compile(
    r"^(.*?)\s+(" + _DATE_PAT + r")\s+YES\s+(" + _DATE_ANY + r"|[-\u2013])\s+(.*)$"
)
_TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}


# Radware occasionally challenges even an impersonated handshake; retry a few times.
_FETCH_ATTEMPTS = 3
_FETCH_BACKOFF = 5.0
_WARN_SECTION = "Minnesota WARN Notices"
# "7/30/2026", "2/24/26", "3/24/26 Revised" — the received date follows the link.
_LIST_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")
_REVISION_RE = re.compile(r"\s*\(revis(?:ion|ed)[^)]*\)\s*$", re.I)


class MNScraper:
    state = "MN"
    source_url = _PAGE_URL
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        """GET the Layoff Resources page with a Chrome TLS fingerprint."""
        import time

        last: Exception | None = None
        for attempt in range(1, _FETCH_ATTEMPTS + 1):
            try:
                r = cffi_requests.get(
                    _PAGE_URL, impersonate="chrome", timeout=60, allow_redirects=True
                )
                r.raise_for_status()
                if _WARN_SECTION.encode() in r.content:
                    return r.content
                # Radware challenge pages come back 200 too — retry, then fail loud.
                last = ScrapeFailed(f"MN: '{_WARN_SECTION}' missing (bot challenge?)")
            except RequestException as exc:
                last = exc
            if attempt < _FETCH_ATTEMPTS:
                time.sleep(_FETCH_BACKOFF)
        raise ScrapeFailed(f"MN: GET {_PAGE_URL}: {last}") from last

    def parse(self, raw: bytes) -> list[NoticeRow]:
        rows = _parse_warn_list(raw, self.source_url)
        if rows is None:
            raise ParseFailed(f"MN: no '{_WARN_SECTION}' section on the page")
        return rows


def _parse_warn_list(raw: bytes, source_url: str) -> list[NoticeRow] | None:
    """Rows from the "Minnesota WARN Notices" accordion; None if it's absent.

    A "(Revision)" entry re-files an earlier notice already on the list
    (Pearson's 7/30 original, 9/15 revision), so it's dropped when its base
    employer is listed too; a revision whose original was replaced on the page
    (Nilfisk, listed once as "3/24/26 Revised") is the only record and is kept.
    """
    soup = BeautifulSoup(raw, "html.parser")
    answer = None
    for question in soup.select("div.question"):
        if " ".join(question.get_text().split()) == _WARN_SECTION:
            answer = question.find_next_sibling("div")
            break
    if answer is None:
        return None

    entries: list[tuple[str, bool, date, str]] = []  # (employer, is_revision, date, pdf)
    for li in answer.find_all("li"):
        a = li.find("a", href=True)
        if a is None or not a["href"].lower().endswith(".pdf"):
            continue
        name = " ".join(a.get_text().split())  # also folds the NBSPs DEED uses
        trailing = " ".join(li.get_text().split())[len(name):]
        m = _LIST_DATE_RE.search(trailing)
        if not name or not m:
            continue
        month, day, year = (int(g) for g in m.groups())
        try:
            notice_date = date(year + 2000 if year < 100 else year, month, day)
        except ValueError:
            continue
        employer = _REVISION_RE.sub("", name)
        href = a["href"]
        pdf_url = href if href.startswith("http") else _BASE_URL + href
        entries.append((employer, employer != name, notice_date, pdf_url))

    originals = {e.lower() for e, is_rev, _, _ in entries if not is_rev}
    return [
        NoticeRow(
            state="MN",
            employer=employer,
            notice_date=notice_date,
            source_url=source_url,
            raw_notice_url=pdf_url,
        )
        for employer, is_rev, notice_date, pdf_url in entries
        if not (is_rev and employer.lower() in originals)
    ]


def _parse_pdf(pdf_bytes: bytes, url: str) -> list[NoticeRow]:
    """Parse one DEED monthly PDF. Returns only WARN Act=YES rows.

    DEED suffixes the report year onto some Layoff Name cells
    ("Zeco Systems Inc 2025"); strip it so live-scraped rows hash identically
    to backfilled ones (the archive-word parser strips the same suffix).
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            rows = _parse_clean_table(pdf, url) or _parse_text_lines(pdf, url)
    except Exception:
        return []
    for row in rows:
        row.employer = _TRAILING_YEAR_RE.sub("", row.employer)
    return rows


# ---------------------------------------------------------------------------
# Historical backfill (2015+)
#
# DEED report naming drifted: monthly PDFs are "mass-layoff-summary*" (2015-16),
# "plant-closing-*" (2022) or "plant-closing-mass-layoff-warn-*" (2023+);
# 2018-2021 published one annual summary each ("mass-layoff-summary-2018",
# "2019-mass-layoffs", "2020-mass-layoff-report",
# "plant-closing-mass-layoff-2021"), and 2022-2024 also publish a cumulative
# year-end roll-up alongside the monthlies — but that roll-up glues the
# employer cell and doubles counts, so _drop_cumulative_reports skips it (the
# monthlies are the clean source). One broad CDX query catches all eras;
# non-report PDFs parse to 0 rows and are skipped.
#
# Pre-2025 files (all eras) are parsed by the word-position parser below —
# pdfplumber's table extraction sees only ghost grids in them, and plain text
# extraction glues employer+city+industry into one run. 2025+ files keep the
# live parser chain so backfilled rows hash identically to live-scraped ones.
# ---------------------------------------------------------------------------

_ARCHIVE_NAME_RE = re.compile(r"(plant-closing|mass-layoff)", re.I)
# A filename carries a month component if it names a month (full or 3-letter)
# or an MMYY token (2015-16 style, matched by _FILE_MMYY_RE below). Cumulative
# year-end roll-ups have neither — just a bare YYYY.
_MONTH_SUBSTR_RE = re.compile(
    r"jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?"
    r"|aug(ust)?|sep(tember)?|oct(ober)?|nov(ember)?|dec(ember)?",
    re.I,
)
# Era-era PDFs glue the report year onto the employer cell
# ("National Recoveries 2021", "Fool Me Once bar, 2024.") — strip it so rows
# hash like monthly-era rows.
_TRAILING_YEAR_RE = re.compile(r"\s+20\d{2}$")
_ARCHIVE_TRAILING_YEAR_RE = re.compile(r"[\s,]*[-\u2013\u2014]?\s*20\d{2}[.,]?$")


def _discover_archive_pdf_urls() -> list[str]:
    """Wayback replay URLs for every monthly DEED plant-closing PDF archived.

    Returns ``web.archive.org/web/{ts}id_/{original}`` URLs (original bytes) —
    mn.gov removes old asset files, so pre-2022 originals 404 or serve an HTML
    error page while the Wayback snapshots remain intact.
    """
    entries = _cdx_query(
        {
            "url": "mn.gov/deed/assets/*",
            "output": "json",
            "fl": "original,timestamp",
            # Server-side regex filter — without it the 5000-entry limit
            # truncates the /deed/assets/ prefix scan before our PDFs.
            "filter": [
                "statuscode:200",
                r"original:.*(plant-closing|mass-layoff).*\.pdf",
            ],
            "collapse": "urlkey",
            "limit": 5000,
        }
    )

    by_original: dict[str, str] = {}
    for entry in entries[1:]:  # skip header row
        if len(entry) < 2:
            continue
        url, ts = entry[0], entry[1]
        if not url.endswith(".pdf") or not _ARCHIVE_NAME_RE.search(url) or url in by_original:
            continue
        by_original[url] = f"https://web.archive.org/web/{ts}id_/{url}"
    return _drop_cumulative_reports(by_original)


def _archive_file_name(url: str) -> str:
    """Filename stem without the trailing ``_tcm1045-NNNNNN`` asset token."""
    return url.rsplit("/", 1)[-1].split("_tcm")[0]


def _has_month_component(name: str) -> bool:
    """True if the report filename names a specific month (vs a bare year)."""
    return bool(_MONTH_SUBSTR_RE.search(name) or _FILE_MMYY_RE.search(name))


def _drop_cumulative_reports(by_original: dict[str, str]) -> list[str]:
    """Drop cumulative year-end roll-up PDFs when the year also has monthlies.

    2022-2024 publish a year-end roll-up (``plant-closing-mass-layoff-2022``,
    ``...-warn-report-2024``) — a bare YYYY, no month component — alongside the
    monthlies. It re-lists every filing with glued employer cells and doubled
    counts, so ingesting it duplicates the monthly rows. Years whose only files
    are monthless (the 2018-2021 annual summaries) are kept — those are the
    sole source for their year.
    """
    years_with_month = {
        _archive_file_year(u)
        for u in by_original
        if _has_month_component(_archive_file_name(u))
    }
    kept: list[str] = []
    for u in sorted(by_original):
        year = _archive_file_year(u)
        if year in years_with_month and not _has_month_component(_archive_file_name(u)):
            log.info("MN: skipping cumulative roll-up %s", _archive_file_name(u))
            continue
        kept.append(by_original[u])
    return kept


# Report year from the filename (the trailing "_tcm1045-NNNNNN" asset token is
# stripped first — its digits would otherwise read as months/years). 2015-16
# files may carry only a numeric MMYY token ("summary0715" = July 2015).
_FILE_YEAR_RE = re.compile(r"20(1[5-9]|2\d)")
_FILE_MMYY_RE = re.compile(r"(?<!\d)(0[1-9]|1[0-2])(1[5-9]|2\d)(?!\d)")
# 2025+ files parse via the live chain (identical hashing with live rows);
# everything older goes to the word-position archive parser.
_ARCHIVE_WORDS_MAX_YEAR = 2024


def _archive_file_year(url: str) -> int | None:
    name = url.rsplit("/", 1)[-1].split("_tcm")[0]
    m = _FILE_YEAR_RE.search(name)
    if m:
        return int(m.group(0))
    m = _FILE_MMYY_RE.search(name)
    if m:
        return 2000 + int(m.group(2))
    return None


def _parse_archive_pdf(pdf_bytes: bytes, url: str) -> list[NoticeRow]:
    """Parse a historical DEED PDF, dispatching on the report's era."""
    year = _archive_file_year(url)
    if year is not None and year <= _ARCHIVE_WORDS_MAX_YEAR:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                return _parse_archive_words(pdf, url)
        except Exception:
            return []
    # 2025+ files use the live parser chain (identical hashing with live rows);
    # _parse_pdf already strips the DEED trailing report year.
    return _parse_pdf(pdf_bytes, url)


# ---------------------------------------------------------------------------
# Word-position parser for the 2015-2024 archive eras.
#
# Every era prints the same line-oriented report — only the column set drifts
# (2015-16 monthlies have Provider/no Layoff Type; WARN Received appears 2021;
# 2016-2019 order Industry before Layoff Start; ...). Deriving column x-bounds
# from the header words handles all of them with one parser, and cleanly
# splits the employer / city / industry runs that text extraction glues.
# ---------------------------------------------------------------------------

_RR_SECTION_RE = re.compile(r"RR Start Date:\s*([A-Za-z]+)\s+(20\d{2})", re.I)
_MD_ONLY_RE = re.compile(r"^\d{1,2}/\d{1,2}$")
_DATE_TOKEN_RE = re.compile(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$")
_INT_TOKEN_RE = re.compile(r"^\d[\d,]*$")
_MONTH_NUM = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
# Max vertical distance (pt) between stacked header lines, and max horizontal
# gap (pt) between words of one header label. Lines carrying any numeric token
# (dates, counts, report years) are never header lines — that keeps section,
# totals, title and data lines out of the band.
_HDR_BAND = 24
_HDR_GAP = 7
_NUMERIC_TOKEN_RE = re.compile(r"^[\d,./()-]*\d[\d,./()-]*$")
# Values sit at or right of their column label; small slack for rounding.
_COL_SLACK = 3

# Known header labels across all 2015-2024 eras, longest-first. Dense
# single-line headers (2023-24) leave inter-column gaps as small as
# within-label gaps, so geometric clustering alone can't split them — clusters
# are re-split by greedy vocabulary match instead.
_HEADER_VOCAB: list[tuple[str, ...]] = [
    tuple(v.split())
    for v in (
        "total affected workers",
        "layoff start date",
        "account: industry",
        "affected workers",
        "account: city",
        "layoff status",
        "warn received",
        "layoff count",
        "layoff start",
        "layoff name",
        "layoff type",
        "taa related",
        "taa status",
        "warn act",
        "industry",
        "provider",
        "city",
        "taa",
    )
]


def _lines_by_top(words: list[dict]) -> list[list[dict]]:
    """Group words into visual lines (top within 2pt), each x-sorted."""
    lines: list[tuple[float, list[dict]]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0] - w["top"]) <= 2:
            lines[-1][1].append(w)
        else:
            lines.append((w["top"], [w]))
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in lines]


def _split_by_vocab(words: list[dict]) -> list[tuple[float, str]]:
    """Greedily re-split one geometric cluster into known header labels."""
    ordered = sorted(words, key=lambda w: (w["top"], w["x0"]))
    tokens = [w["text"].lower().lstrip("*") for w in ordered]
    out: list[tuple[float, str]] = []
    i = 0
    while i < len(tokens):
        label = next(
            (v for v in _HEADER_VOCAB if tuple(tokens[i : i + len(v)]) == v), None
        )
        if label:
            out.append((min(w["x0"] for w in ordered[i : i + len(label)]), " ".join(label)))
            i += len(label)
        else:
            i += 1  # stray token (wrapped fragment) — ignore
    return out or [(min(w["x0"] for w in words), " ".join(tokens))]


def _header_band(lines: list[list[dict]], anchor_top: float) -> list[list[dict]]:
    """Lines belonging to the stacked header block around the anchor."""
    return [
        ws
        for ws in lines
        if abs(ws[0]["top"] - anchor_top) <= _HDR_BAND
        and not any(_NUMERIC_TOKEN_RE.match(w["text"]) for w in ws)
    ]


def _header_columns(lines: list[list[dict]], anchor_idx: int) -> list[tuple[float, str]]:
    """Cluster the stacked header block around the anchor line into columns.

    Returns [(min_x0, normalized label), ...] sorted by x position. Words on
    one line split into segments at gaps > _HDR_GAP; segments from stacked
    lines merge when their x-ranges overlap ("WARN" over "Act"); each merged
    cluster is then re-split against the label vocabulary.
    """
    anchor_top = lines[anchor_idx][0]["top"]
    segments: list[dict] = []  # {x0, x1, words}
    for ws in _header_band(lines, anchor_top):
        seg: dict | None = None
        for w in ws:
            if seg is not None and w["x0"] - seg["x1"] <= _HDR_GAP:
                seg["x1"] = max(seg["x1"], w["x1"])
                seg["words"].append(w)
            else:
                seg = {"x0": w["x0"], "x1": w["x1"], "words": [w]}
                segments.append(seg)
    # Merge segments across lines while their x-ranges overlap.
    merged: list[dict] = []
    for seg in sorted(segments, key=lambda s: s["x0"]):
        hit = next((m for m in merged if seg["x0"] < m["x1"] and m["x0"] < seg["x1"]), None)
        if hit:
            hit["x0"] = min(hit["x0"], seg["x0"])
            hit["x1"] = max(hit["x1"], seg["x1"])
            hit["words"].extend(seg["words"])
        else:
            merged.append(seg)
    cols: list[tuple[float, str]] = []
    for m in sorted(merged, key=lambda s: s["x0"]):
        cols.extend(_split_by_vocab(m["words"]))
    return sorted(cols)


def _recover_count(rec: dict[int, list[str]], roles: dict[str, int]) -> None:
    """Recover a right-aligned Affected-Workers count that mis-bucketed left.

    The count column is right-aligned, so a small value can sit a few points
    left of its header x-start and fall into the preceding (TAA) column,
    leaving the count cell empty. When that happens, move a trailing integer
    from the nearest non-empty column left of count into it. In-place; a no-op
    when the count already parsed or no integer is adjacent.
    """
    if "count" not in roles or rec.get(roles["count"]):
        return
    for i in range(roles["count"] - 1, -1, -1):
        toks = rec.get(i)
        if not toks:
            continue
        if _INT_TOKEN_RE.match(toks[-1]):
            rec[roles["count"]] = [toks[-1]]
            rec[i] = toks[:-1]
        break  # only inspect the nearest non-empty column


def _parse_archive_words(pdf: pdfplumber.PDF, url: str) -> list[NoticeRow]:  # type: ignore[name-defined]
    """Parse a 2015-2024 era report by assigning words to header columns."""
    starts: list[float] = []
    roles: dict[str, int] = {}
    section: tuple[int, int] | None = None  # (year, month) of "RR Start Date:"
    open_rec: dict[int, list[str]] | None = None
    rows: list[NoticeRow] = []

    def _close() -> None:
        nonlocal open_rec
        if open_rec is None:
            return
        rec, open_rec = open_rec, None

        def cell(role: str) -> str | None:
            i = roles.get(role)
            return " ".join(rec[i]) if i is not None and rec.get(i) else None

        if (cell("warn") or "").upper() != "YES":
            return
        # A Layoff Type value can print left of its own header label and land
        # in the WARN Received column ("4/4/2024 Workforce") — keep only the
        # leading date/dash in Received and shift the rest into Type.
        if "received" in roles and rec.get(roles["received"]):
            toks = rec[roles["received"]]
            keep = 1 if _DATE_TOKEN_RE.match(toks[0]) or toks[0] in ("-", "\u2013") else 0
            if len(toks) > keep:
                if "type" in roles:
                    rec.setdefault(roles["type"], [])[:0] = toks[keep:]
                rec[roles["received"]] = toks[:keep]
        _recover_count(rec, roles)
        employer = as_str(_ARCHIVE_TRAILING_YEAR_RE.sub("", cell("name") or ""))
        if not employer:
            return
        effective_date = as_date(cell("start"))
        recv_raw = cell("received")
        notice_date = None
        if recv_raw and _MD_ONLY_RE.match(recv_raw):
            yr = effective_date.year if effective_date else (section or (date.today().year,))[0]
            recv_raw = f"{recv_raw}/{yr}"
        if recv_raw:
            notice_date = as_date(recv_raw)
        if notice_date is None:
            notice_date = effective_date
        if notice_date is None and section:
            notice_date = date(section[0], section[1], 1)
        industry = cell("industry")
        rows.append(
            NoticeRow(
                state="MN",
                employer=employer,
                notice_date=notice_date,
                effective_date=effective_date,
                layoff_count=as_int(cell("count")),
                closure_type=as_str(cell("type")),
                city=as_str(cell("city")),
                source_url=url,
                extra={"industry": industry} if industry else {},
            )
        )

    for page in pdf.pages:
        _close()  # rows never wrap across pages; don't absorb next-page chrome
        lines = _lines_by_top(page.extract_words())
        header_tops: set[float] = set()
        for idx, ws in enumerate(lines):
            text = " ".join(w["text"] for w in ws)
            if text.startswith(("*", "�")):
                continue  # footnote blocks
            if "Layoff Name" in text:
                cols = _header_columns(lines, idx)
                labels = [label for _, label in cols]
                starts = [x for x, _ in cols]
                roles = {}
                for role, pred in (
                    ("name", lambda s: "name" in s),
                    ("city", lambda s: "city" in s),
                    ("industry", lambda s: "industry" in s),
                    ("start", lambda s: "start" in s),
                    ("warn", lambda s: "warn" in s and "act" in s),
                    ("received", lambda s: "received" in s),
                    ("type", lambda s: "type" in s),
                    ("count", lambda s: "affected" in s),
                ):
                    i = next((i for i, s in enumerate(labels) if pred(s)), None)
                    if i is not None:
                        roles[role] = i
                header_tops = {
                    band[0]["top"] for band in _header_band(lines, ws[0]["top"])
                }
                continue
            if ws[0]["top"] in header_tops:
                continue
            if text.startswith("Grand Totals"):
                _close()
                return rows
            m = _RR_SECTION_RE.search(text)
            if m:
                _close()
                month = _MONTH_NUM.get(m.group(1).lower())
                if month:
                    section = (int(m.group(2)), month)
                continue
            if not starts or {"name", "warn"} - roles.keys():
                continue
            by_col: dict[int, list[str]] = {}
            for w in ws:
                col = bisect_right(starts, w["x0"] + _COL_SLACK) - 1
                if col >= 0:
                    by_col.setdefault(col, []).append(w["text"])
            warn_words = by_col.get(roles["warn"], [])
            if warn_words and warn_words[0] in ("YES", "NO"):
                _close()
                if len(warn_words) > 1 and "received" in roles:
                    # A WARN Received date can print left of its own header
                    # label and land in the WARN Act column — move it over.
                    by_col[roles["warn"]] = warn_words[:1]
                    by_col.setdefault(roles["received"], [])[:0] = warn_words[1:]
                open_rec = by_col
            elif open_rec is not None:
                for col, texts in by_col.items():
                    open_rec.setdefault(col, []).extend(texts)
    _close()
    return rows


def _parse_clean_table(pdf: pdfplumber.PDF, url: str) -> list[NoticeRow]:  # type: ignore[name-defined]
    """Try the 2026-style clean 10-column table format."""
    rows: list[NoticeRow] = []
    header: dict[str, int] | None = None

    for page in pdf.pages:
        table = page.extract_table(_TABLE_SETTINGS)
        if not table:
            continue

        for row in table:
            if not row or len(row) < 5:
                continue
            # Detect header row (contains "Layoff Name" or "WARN" in a cell)
            clean = [str(c or "").replace("\n", " ").strip() for c in row]
            is_header_row = any("Layoff Name" in c or ("WARN" in c and "Act" in c) for c in clean)
            if header is None or is_header_row:
                # Build column map from this row if it looks like a header
                if any("Layoff Name" in c for c in clean):
                    merged = [" ".join(c.split()) for c in clean]
                    header = {n: i for i, n in enumerate(merged)}
                    continue

            if header is None:
                continue

            # Require well-formed row: no excessive None merging
            none_count = sum(1 for c in row if c is None)
            if none_count > len(row) // 2:
                continue

            warn_idx = next(
                (i for n, i in header.items() if "WARN" in n and "Act" in n), None
            )
            if warn_idx is None:
                continue
            if warn_idx >= len(clean) or clean[warn_idx].upper() != "YES":
                continue

            # Extract fields
            name_idx = next((i for n, i in header.items() if "Layoff Name" in n), 0)
            city_idx = next((i for n, i in header.items() if "City" in n), None)
            start_idx = next((i for n, i in header.items() if "Start" in n), None)
            recv_idx = next((i for n, i in header.items() if "Received" in n), None)
            type_idx = next((i for n, i in header.items() if "Layoff Type" in n), None)
            workers_idx = next(
                (i for n, i in header.items() if "Affected" in n or "Workers" in n), None
            )

            employer = as_str(clean[name_idx] if name_idx < len(clean) else "")
            if not employer:
                continue

            notice_date = (
                as_date(clean[recv_idx]) if recv_idx is not None and recv_idx < len(clean) else None
            )
            effective_date = (
                as_date(clean[start_idx])
                if start_idx is not None and start_idx < len(clean)
                else None
            )
            city = (
                as_str(clean[city_idx]) if city_idx is not None and city_idx < len(clean) else None
            )
            closure_type = (
                as_str(clean[type_idx]) if type_idx is not None and type_idx < len(clean) else None
            )
            layoff_count = (
                as_int(clean[workers_idx])
                if workers_idx is not None and workers_idx < len(clean)
                else None
            )

            rows.append(
                NoticeRow(
                    state="MN",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    city=city,
                    source_url=url,
                )
            )

    return rows


def _parse_text_lines(pdf: pdfplumber.PDF, url: str) -> list[NoticeRow]:  # type: ignore[name-defined]
    """Fallback: 2025-style wide table — parse text line by line."""
    rows: list[NoticeRow] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            m = _WARN_YES_RE.match(line)
            if not m:
                continue
            prefix, start_date_raw, recv_raw, _rest = m.groups()
            # The prefix contains "Name City Industry" but we can't reliably split them.
            # Use the whole prefix as employer name and skip city extraction.
            employer = as_str(prefix)
            if not employer:
                continue
            effective_date = as_date(start_date_raw)
            # WARN Received in 2025 PDFs may be "M/D" (no year) — infer year from effective_date
            notice_date = None
            if recv_raw and recv_raw not in ("-", "\u2013"):
                if re.match(r"^\d{1,2}/\d{1,2}$", recv_raw):
                    # Append year from effective_date (or current year as fallback)
                    yr = effective_date.year if effective_date else date.today().year
                    recv_raw = f"{recv_raw}/{yr}"
                notice_date = as_date(recv_raw)
            # Layoff count: last number on the line
            nums = re.findall(r"\b(\d+)\b", _rest)
            layoff_count = as_int(nums[-1]) if nums else None

            # When WARN Received is missing, fall back to effective_date so notice_date
            # is always populated for WARN Act=YES rows (we know a notice was filed).
            rows.append(
                NoticeRow(
                    state="MN",
                    employer=employer,
                    notice_date=notice_date or effective_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    source_url=url,
                )
            )
    return rows


register(MNScraper())

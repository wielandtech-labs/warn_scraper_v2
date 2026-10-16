"""Benchmark per-state, per-year notice counts against LaborCurrent.

Automates the manual refresh in docs/coverage-vs-aggregators.md. It fetches our
yearly counts from the public API (``/api/stats/over-time?bucket=year``), and
LaborCurrent's from the "All-Time Layoff Trend" chart on each
``laborcurrent.com/layoffs/<state>`` page. It then prints every state-year where
they hold more notices than we do. Per the policy in historical-sources.md, an
aggregator is only a completeness yardstick and is never ingested. A shortfall
here is a lead to chase at the state's own source, not a row to copy.

Counts are not like-for-like. LaborCurrent keeps worksite and amendment rows
that we collapse or mark superseded, and it includes MS "Non-WARN" rows that our
aggregates exclude. Their chart is quarterly before the last 24 months and
monthly after, and both kinds of bucket fold into the same year. A shortfall in
a recent, well-covered year is therefore usually a counting difference. A year
where we hold zero, or a run of years well short, is usually a real gap.

LaborCurrent's robots.txt allows these pages and asks for a 2s crawl delay,
which ``fetch_reference`` honours (51 pages, about 2 minutes).

Run with:
    python -m warn_v2.scripts.aggregator_benchmark [--min-gap 10] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass

import httpx

from warn_v2.states import STATE_NAMES

OURS_BASE = "https://warnindex.com"
REFERENCE_BASE = "https://laborcurrent.com"
CRAWL_DELAY_S = 2.0
_UA = {"User-Agent": "warnindex-coverage-benchmark/1.0 (+https://warnindex.com)"}

_LABELS_RE = re.compile(r"labels:\s*(\[[^\]]*\])")
_DATA_RE = re.compile(r'"data":\s*(\[[^\]]*\])')


@dataclass
class Gap:
    state: str
    year: int
    ours: int
    reference: int

    @property
    def shortfall(self) -> int:
        return self.reference - self.ours


def reference_slug(state: str) -> str:
    return STATE_NAMES[state].lower().replace(" ", "-")


def parse_trend_chart(html: str, slug: str) -> dict[int, int] | None:
    """Yearly notice counts from a LaborCurrent state page's trend chart.

    The chart is a Chart.js literal whose labels are "Q1 2009" or "Nov 2024",
    and whose first dataset is "WARN Notices". Returns None when the page has
    no trend chart; LaborCurrent omits it for states with no data.
    """
    start = html.find(f"state-{slug}-trend'")
    if start < 0:
        return None
    chart = html[start : html.find("</script>", start)]
    labels_m, data_m = _LABELS_RE.search(chart), _DATA_RE.search(chart)
    if not labels_m or not data_m:
        raise ValueError(f"{slug}: trend chart found but labels/data unparseable")
    labels, notices = json.loads(labels_m.group(1)), json.loads(data_m.group(1))
    if len(labels) != len(notices):
        raise ValueError(f"{slug}: {len(labels)} labels vs {len(notices)} values")
    years: dict[int, int] = {}
    for label, n in zip(labels, notices, strict=True):
        year = int(re.search(r"\d{4}", label).group(0))  # type: ignore[union-attr]
        years[year] = years.get(year, 0) + int(n)
    return years


def find_gaps(
    ours: dict[str, dict[int, int]],
    reference: dict[str, dict[int, int]],
    *,
    min_gap: int,
) -> list[Gap]:
    """State-years where the reference exceeds us by at least ``min_gap``.

    A year we hold nothing for also counts once the reference has 3 or more
    notices, because a zero year is a hole whatever its size. Results are sorted
    by state, then year.
    """
    gaps = []
    for state, ref_years in reference.items():
        our_years = ours.get(state, {})
        for year, ref_n in ref_years.items():
            our_n = our_years.get(year, 0)
            short = ref_n - our_n
            if short >= min_gap or (our_n == 0 and short >= 3):
                gaps.append(Gap(state, year, our_n, ref_n))
    return sorted(gaps, key=lambda g: (g.state, g.year))


def fetch_ours(client: httpx.Client) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {}
    for state in STATE_NAMES:
        r = client.get(
            f"{OURS_BASE}/api/stats/over-time", params={"bucket": "year", "state": state}
        )
        r.raise_for_status()
        out[state] = {int(p["period"]): p["notice_count"] for p in r.json()}
    return out


def fetch_reference(client: httpx.Client) -> dict[str, dict[int, int]]:
    out: dict[str, dict[int, int]] = {}
    for i, state in enumerate(STATE_NAMES):
        if i:
            time.sleep(CRAWL_DELAY_S)
        slug = reference_slug(state)
        r = client.get(f"{REFERENCE_BASE}/layoffs/{slug}")
        r.raise_for_status()
        years = parse_trend_chart(r.text, slug)
        if years is not None:
            out[state] = years
    return out


def _report(gaps: list[Gap], ours: dict, reference: dict) -> str:
    lines = []
    our_total = sum(sum(y.values()) for y in ours.values())
    ref_total = sum(sum(y.values()) for y in reference.values())
    lines.append(f"ours {our_total:,} notices; reference trend charts {ref_total:,}")
    lines.append(f"{len(gaps)} state-years short, {sum(g.shortfall for g in gaps):,} notices")
    by_state: dict[str, list[Gap]] = {}
    for g in gaps:
        by_state.setdefault(g.state, []).append(g)
    ranked = sorted(by_state.items(), key=lambda kv: -sum(g.shortfall for g in kv[1]))
    for state, sg in ranked:
        cells = " ".join(
            f"{g.year}:{g.ours}/{g.reference}{'*' if g.ours == 0 else ''}" for g in sg
        )
        lines.append(f"{state} +{sum(g.shortfall for g in sg):,}  {cells}")
    lines.append("cells are year:ours/reference; * = we hold zero that year")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-gap", type=int, default=10, help="smallest shortfall to list")
    ap.add_argument("--json", action="store_true", help="emit gaps as JSON")
    args = ap.parse_args(argv)
    with httpx.Client(headers=_UA, timeout=60, follow_redirects=True) as client:
        ours = fetch_ours(client)
        reference = fetch_reference(client)
    gaps = find_gaps(ours, reference, min_gap=args.min_gap)
    if args.json:
        print(json.dumps([asdict(g) | {"shortfall": g.shortfall} for g in gaps], indent=2))
    else:
        print(_report(gaps, ours, reference))
    return 0


if __name__ == "__main__":
    sys.exit(main())

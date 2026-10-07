"""Tests for the /layoff-sentiment skill's validator (.claude/skills/...),
the deterministic gate every Claude-written report must pass."""
from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from warn_v2.db.models import Notice

_VALIDATE = Path(__file__).resolve().parents[1] / ".claude/skills/layoff-sentiment/validate.py"
_spec = importlib.util.spec_from_file_location("layoff_sentiment_validate", _VALIDATE)
assert _spec and _spec.loader
validate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_mod)

AS_OF = date(2026, 10, 5)


@pytest.fixture
def doc(db) -> dict:
    """A real payloads.json shape for CA, built by the cron's own code."""
    from warn_v2.reports.generate import build_state_payload

    for i, (days_ago, county_layoffs) in enumerate([(10, 120), (20, 80), (100, 40)] * 2):
        db.add(
            Notice(
                notice_id=f"val_{i}",
                state="CA",
                employer=f"Employer {i}",
                notice_date=AS_OF - timedelta(days=days_ago),
                layoff_count=county_layoffs,
            )
        )
    db.commit()
    return {
        "schema": 1,
        "as_of": AS_OF.isoformat(),
        "jurisdictions": {"CA": build_state_payload(db, "CA", as_of=AS_OF)},
        "industries": {},
    }


def _pct(v) -> str:
    return "no comparable activity" if v is None else f"{v}%"


def _report(p: dict, as_of: str, sentiment: str) -> str:
    """CA.md written the way SKILL.md's template says to."""
    t, s, y, pc = p["totals"], p["same_window_last_year"], p["year_over_year"], p["pct_change"]
    month_rows = "\n".join(
        f"| {m['month']} | {m['notices']} | {m['layoffs']} | {m['layoffs_year_earlier']} |"
        for m in p["monthly"]
    )
    county_rows = "\n".join(
        f"| {r['name']} | {r['notices_current']} | {r['layoffs_current']} "
        f"| {r['layoffs_prior']} | {r['delta_layoffs']:+d} "
        f"| {'new' if r['pct_change'] is None else str(r['pct_change']) + '%'} |"
        for r in p["top_counties"]
    )
    return f"""# {p['state_name']} ({p['state']}) — WARN Layoff Trends

_Generated {as_of} · Current window {p['current_window']['start']} → \
{p['current_window']['end']} vs prior {p['prior_window']['start']} → \
{p['prior_window']['end']} · same window last year {s['start']} → {s['end']}_

## Summary

| Metric | Current 90d | Prior 90d | Same 90d last yr | Trailing 12mo | Prior 12mo |
|---|---:|---:|---:|---:|---:|
| Notices | {t['notices_current']} | {t['notices_prior']} | {s['notices']} \
| {y['notices_trailing_12mo']} | {y['notices_prior_12mo']} |
| Workers affected | {t['layoffs_current']:,} | {t['layoffs_prior']} | {s['layoffs']} \
| {y['layoffs_trailing_12mo']} | {y['layoffs_prior_12mo']} |

**Job losses vs prior window: {_pct(pc['layoffs_vs_prior_window'])} · vs same window \
last year: {_pct(pc['layoffs_vs_same_window_last_year'])}**

## Sentiment

{sentiment}

## Where layoffs are shifting — by county

| County | Notices | Workers affected | Prior workers | Δ workers | Δ% |
|---|---:|---:|---:|---:|---:|
{county_rows}

## Monthly trend (last 12 months)

| Month | Notices | Workers affected | Same month last yr |
|---|---:|---:|---:|
{month_rows}

---

_Figures computed from non-superseded WARN notices. Written analysis by Claude from \
the {as_of} figures._
"""


def _check(tmp_path, doc, text) -> list[str]:
    path = tmp_path / "CA.md"
    path.write_text(text, encoding="utf-8")
    return validate_mod.validate(path, doc)


def _good_sentiment(p: dict) -> str:
    t = p["totals"]
    return (
        f"Job losses in California rose to {t['layoffs_current']} in the current "
        f"90-day window from {t['layoffs_prior']} in the prior window. Activity "
        f"remained concentrated in a few counties."
    )


def test_template_report_passes(tmp_path, doc):
    p = doc["jurisdictions"]["CA"]
    assert _check(tmp_path, doc, _report(p, doc["as_of"], _good_sentiment(p))) == []


def test_main_exit_codes(tmp_path, doc, capsys):
    p = doc["jurisdictions"]["CA"]
    payloads = tmp_path / "payloads.json"
    payloads.write_text(json.dumps(doc), encoding="utf-8")
    report = tmp_path / "CA.md"
    report.write_text(_report(p, doc["as_of"], _good_sentiment(p)), encoding="utf-8")
    assert validate_mod.main([str(payloads), str(report)]) == 0
    report.write_text(_report(p, doc["as_of"], "Losses grew."), encoding="utf-8")
    assert validate_mod.main([str(payloads), str(report)]) == 1
    assert "checked=1 failed=1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("sentiment", "expected"),
    [
        ("Layoffs added 120 jobs to the tally.", "banned growth word 'added'"),
        ("Job losses rose to 987654.", "number 987654 is not in the payload"),
        ("Job losses rose sharply on 2019-01-01.", "date 2019-01-01 is not in the payload"),
        ("See [the source](https://x.test).", "markdown link"),
        ("Losses are *notable* here.", "*single* italics"),
        ("Run `warn-v2` for more.", "inline code"),
        ("1. First point", "numbered list"),
        ("- a list in Sentiment", "plain prose"),
        ("word " * 251, "Sentiment is 251 words"),
    ],
)
def test_violations_are_caught(tmp_path, doc, sentiment, expected):
    p = doc["jurisdictions"]["CA"]
    problems = _check(tmp_path, doc, _report(p, doc["as_of"], sentiment))
    assert any(expected in msg for msg in problems), problems


def test_structure_checks(tmp_path, doc):
    p = doc["jurisdictions"]["CA"]
    good = _report(p, doc["as_of"], _good_sentiment(p))

    wrong_h1 = good.replace("# California (CA)", "# California", 1)
    assert any("first line" in m for m in _check(tmp_path, doc, wrong_h1))

    stale = good.replace(f"_Generated {doc['as_of']}", "_Generated 2026-09-28", 1)
    assert any("second line" in m for m in _check(tmp_path, doc, stale))

    no_monthly = good.replace("## Monthly trend", "## Monthly", 1)
    assert any("Monthly trend" in m for m in _check(tmp_path, doc, no_monthly))

    ragged = good.replace("| Notices | ", "| Notices | | ", 1)
    assert any("ragged" in m for m in _check(tmp_path, doc, ragged))


def test_payload_percentage_may_be_cited_at_lower_precision(tmp_path, doc):
    p = doc["jurisdictions"]["CA"]
    pct = p["pct_change"]["layoffs_vs_prior_window"]
    assert pct is not None
    ok = _report(p, doc["as_of"], f"Job losses rose {round(pct)}% from the prior window.")
    assert _check(tmp_path, doc, ok) == []


def test_top_level_list_after_blank_line_is_fine(tmp_path, doc):
    # Regression: the nested-list check once matched "\n- " across a blank line.
    p = doc["jurisdictions"]["CA"]
    text = _report(p, doc["as_of"], _good_sentiment(p)).replace(
        "## Where layoffs", "## Analysis\n\nWorth watching:\n\n- the trend\n\n## Where layoffs", 1
    )
    assert _check(tmp_path, doc, text) == []
    nested = text.replace("- the trend", "- the trend\n  - a sub-point", 1)
    assert any("nested list" in m for m in _check(tmp_path, doc, nested))


def test_county_name_with_banned_substring_in_table_is_fine(tmp_path, doc):
    # Banned-word scanning skips table rows: scraped place names are data.
    p = doc["jurisdictions"]["CA"]
    p["top_counties"][0]["name"] = "Grow County"
    text = _report(p, doc["as_of"], _good_sentiment(p))
    assert _check(tmp_path, doc, text) == []

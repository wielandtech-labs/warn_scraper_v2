"""Tests for sentiment-report markdown rendering and narrative sanitization."""
from __future__ import annotations

from datetime import date

from warn_v2.reports.aggregate import DeltaRow, StateAggregates
from warn_v2.reports.forecast import Forecast, ForecastPoint
from warn_v2.reports.generate import write_report
from warn_v2.reports.industry import SectorAggregates
from warn_v2.reports.render import (
    MAX_NARRATIVE_CHARS,
    render_industry_report,
    render_report,
    sanitize_narrative,
)


def _agg(**overrides) -> StateAggregates:
    base = dict(
        state="CA",
        state_name="California",
        as_of=date(2026, 7, 1),
        cur_start=date(2026, 4, 3),
        cur_end=date(2026, 7, 1),
        prior_start=date(2026, 1, 3),
        prior_end=date(2026, 4, 2),
        season_start=date(2025, 4, 3),
        season_end=date(2025, 7, 1),
        cur_notices=10,
        cur_layoffs=500,
        prior_notices=8,
        prior_layoffs=300,
        season_notices=7,
        season_layoffs=310,
        yoy_cur_notices=40,
        yoy_cur_layoffs=2000,
        yoy_prior_notices=35,
        yoy_prior_layoffs=1800,
        closure_split={"Layoff": 7, "Closure": 3},
        counties=[
            DeltaRow(
                key="Alameda", name="Alameda", cur_notices=5, cur_layoffs=400,
                prior_notices=2, prior_layoffs=100,
            ),
            DeltaRow(
                key="Kern", name="Kern", cur_notices=1, cur_layoffs=100,
                prior_notices=0, prior_layoffs=0,
            ),
        ],
        sectors=[
            DeltaRow(
                key="31-33", name="Manufacturing", cur_notices=4, cur_layoffs=300,
                prior_notices=3, prior_layoffs=150,
            ),
        ],
        monthly=[("2026-05", 4, 200, 90), ("2026-06", 6, 300, 0)],
        naics_coverage_pct=62.0,
    )
    base.update(overrides)
    return StateAggregates(**base)


def _sector_agg(**overrides) -> SectorAggregates:
    base = dict(
        sector="31-33",
        sector_name="Manufacturing",
        as_of=date(2026, 7, 1),
        cur_start=date(2026, 4, 3),
        cur_end=date(2026, 7, 1),
        prior_start=date(2026, 1, 3),
        prior_end=date(2026, 4, 2),
        season_start=date(2025, 4, 3),
        season_end=date(2025, 7, 1),
        cur_notices=10,
        cur_layoffs=500,
        prior_notices=8,
        prior_layoffs=300,
        season_notices=7,
        season_layoffs=310,
        yoy_cur_notices=40,
        yoy_cur_layoffs=2000,
        yoy_prior_notices=35,
        yoy_prior_layoffs=1800,
        states=[
            DeltaRow(
                key="CA", name="California", cur_notices=5, cur_layoffs=400,
                prior_notices=2, prior_layoffs=100,
            ),
        ],
        subsectors=[
            DeltaRow(
                key="311", name="Food Manufacturing", cur_notices=4, cur_layoffs=300,
                prior_notices=3, prior_layoffs=150,
            ),
        ],
        monthly=[("2026-05", 4, 200, 90), ("2026-06", 6, 300, 0)],
        total_cur_notices=100,
    )
    base.update(overrides)
    return SectorAggregates(**base)


# ---------------------------------------------------------------------------
# sanitize_narrative
# ---------------------------------------------------------------------------

def test_sanitize_strips_think_and_demotes_headings():
    raw = "<think>secret chain of thought</think>## Big Heading\nLayoffs rose."
    out = sanitize_narrative(raw)
    assert "secret" not in out
    assert "#" not in out
    assert "Big Heading" in out
    assert "Layoffs rose." in out


def test_sanitize_escapes_html():
    out = sanitize_narrative("Beware <script>alert(1)</script> tags")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_sanitize_collapses_blank_runs_and_truncates():
    out = sanitize_narrative("a\n\n\n\n\nb")
    assert out == "a\n\nb"
    long = "x" * (MAX_NARRATIVE_CHARS + 500)
    assert len(sanitize_narrative(long)) <= MAX_NARRATIVE_CHARS + 1  # + ellipsis


def test_sanitize_truncates_at_sentence_boundary():
    # An overlong narrative is cut at the last full sentence, not mid-thought.
    sentence = "Job losses rose sharply in the county. "
    long = sentence * (MAX_NARRATIVE_CHARS // len(sentence) + 5)
    out = sanitize_narrative(long)
    assert len(out) <= MAX_NARRATIVE_CHARS
    assert out.endswith("in the county.")
    # No sentence boundary in the first half → fall back to the ellipsis cut.
    unbroken = "x" * (MAX_NARRATIVE_CHARS + 500) + "."
    assert sanitize_narrative(unbroken).endswith("…")


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------

def test_render_ok_embeds_sanitized_narrative():
    md = render_report(
        _agg(), "## Trend\nLayoffs <b>rose</b> in Alameda.",
        narrative_status="ok", model="gpt-oss:20b",
    )
    assert md.startswith("# California (CA) — WARN Layoff Trends")
    assert "· same window last year 2025-04-03 → 2025-07-01" in md
    assert "Layoffs &lt;b&gt;rose&lt;/b&gt; in Alameda." in md
    assert "## Trend" not in md  # heading demoted
    assert "Narrative generated by gpt-oss:20b" in md
    # Deterministic tables always present.
    # Summary: cur | prior | Δ | same window last yr | YoY Δ% | 12mo | prior 12mo
    assert "| Notices | 10 | 8 | +2 | 7 | +43% | 40 | 35 |" in md
    assert "| Workers affected | 500 | 300 | +200 | 310 | +61% | 2000 | 1800 |" in md
    assert "| Alameda | 5 | 400 | 100 | +300 | +300% |" in md
    assert "| Kern | 1 | 100 | 0 | +100 | new |" in md
    assert "| Manufacturing | 4 | 300 | 150 | +150 | +100% |" in md
    assert "| 2026-05 | 4 | 200 | 90 |" in md
    assert "| 2026-06 | 6 | 300 | 0 |" in md
    assert "NAICS coverage: 62%" in md
    assert "Current-window notice mix: 7 Layoff · 3 Closure." in md


def _forecast(**overrides) -> Forecast:
    base = dict(
        model="ets-seasonal",
        history_months=36,
        last_history_month="2026-06",
        points=[
            ForecastPoint(
                month="2026-07", notices=12, notices_lo=6, notices_hi=19,
                layoffs=1450, layoffs_lo=700, layoffs_hi=2300,
            ),
            ForecastPoint(
                month="2026-08", notices=10, notices_lo=5, notices_hi=16,
                layoffs=1100, layoffs_lo=500, layoffs_hi=1900,
            ),
        ],
    )
    base.update(overrides)
    return Forecast(**base)


def test_render_without_forecast_is_unchanged():
    md_no_kwarg = render_report(_agg(), None, narrative_status="skipped")
    md_explicit_none = render_report(_agg(), None, narrative_status="skipped", forecast=None)
    assert md_no_kwarg == md_explicit_none
    assert "Outlook" not in md_no_kwarg


def test_render_with_forecast_adds_outlook_section():
    md = render_report(_agg(), None, narrative_status="skipped", forecast=_forecast())
    assert "## Outlook — next 6 months (model estimate)" in md
    assert "| 2026-07 | 12 | 6-19 | 1450 | 700-2300 |" in md
    assert "| 2026-08 | 10 | 5-16 | 1100 | 500-1900 |" in md
    assert "damped trend, seasonal" in md
    assert "36 months of history through 2026-06" in md
    assert "floored at zero" in md
    # The Outlook section renders between the monthly trend and the footer.
    assert md.index("Monthly trend") < md.index("Outlook") < md.index("_Deterministic figures")


def test_render_forecast_model_labels():
    md = render_report(
        _agg(), None, narrative_status="skipped", forecast=_forecast(model="ets-trend")
    )
    assert "exponential smoothing, damped trend)" in md
    assert "damped trend, seasonal" not in md

    md = render_report(
        _agg(), None, narrative_status="skipped", forecast=_forecast(model="ets-level")
    )
    assert "exponential smoothing, level only)" in md


def test_render_insufficient_data():
    md = render_report(
        _agg(cur_notices=1, prior_notices=1), None, narrative_status="insufficient_data"
    )
    assert "Insufficient recent WARN activity in California" in md
    assert "2 notices in the last 180 days" in md


def test_render_llm_unavailable_and_skipped():
    md = render_report(_agg(), None, narrative_status="llm_unavailable", model="gpt-oss:20b")
    assert "Narrative unavailable this week" in md
    assert "Narrative generated by" not in md  # no credit for a missing narrative

    md = render_report(_agg(), None, narrative_status="skipped")
    assert "Narrative generation was skipped" in md


def test_render_seasonal_zero_baseline_cells():
    # No activity in the same window last year → "new"; both zero → "—".
    md = render_report(
        _agg(season_notices=0, season_layoffs=0), None, narrative_status="skipped"
    )
    assert "| Notices | 10 | 8 | +2 | 0 | new | 40 | 35 |" in md
    assert "| Workers affected | 500 | 300 | +200 | 0 | new | 2000 | 1800 |" in md

    md = render_report(
        _agg(
            cur_notices=0, cur_layoffs=0, season_notices=0, season_layoffs=0,
        ),
        None,
        narrative_status="skipped",
    )
    assert "| Notices | 0 | 8 | -8 | 0 | — | 40 | 35 |" in md


def test_render_empty_state():
    md = render_report(
        _agg(
            cur_notices=0, cur_layoffs=0, prior_notices=0, prior_layoffs=0,
            counties=[], sectors=[], monthly=[], closure_split={},
            naics_coverage_pct=0.0,
        ),
        None,
        narrative_status="insufficient_data",
    )
    assert "_No notices in either window._" in md
    assert "_No notices in the last 12 months._" in md


# ---------------------------------------------------------------------------
# render_report — national
# ---------------------------------------------------------------------------

def _national_agg(**overrides):
    states = [
        DeltaRow(
            key="CA", name="California", cur_notices=5, cur_layoffs=400,
            prior_notices=2, prior_layoffs=100,
        ),
    ]
    return _agg(
        state="US", state_name="United States", counties=[], states=states, **overrides
    )


def test_render_national_uses_state_table():
    md = render_report(_national_agg(), None, narrative_status="skipped")
    assert md.startswith("# United States (US) — WARN Layoff Trends")
    assert "## Where layoffs are shifting — by state" in md
    assert "| California | 5 | 400 | 100 | +300 | +300% |" in md
    assert "by county" not in md


# ---------------------------------------------------------------------------
# render_industry_report
# ---------------------------------------------------------------------------

def test_render_industry_scorecard():
    md = render_industry_report(_sector_agg(), "Pressure is rising.", model="gpt-oss:20b")
    assert md.startswith("# Manufacturing (NAICS 31-33) — Industry Scorecard")
    assert "· same window last year 2025-04-03 → 2025-07-01" in md
    # Fixture: layoffs 500/300 → 16.7, yoy 2000/1800 → 44.4, notices 10/8 → 37.5
    # → 0.5*16.7 + 0.3*44.4 + 0.2*37.5 ≈ 29 → Grade D.
    assert "**Score: 29/100 — Grade D (elevated)**" in md
    assert "How this score works" in md
    assert "> Notices attributed to this sector: 10 of 100" in md
    assert "(10%)" in md
    assert "undercount" in md
    assert "Pressure is rising." in md
    assert "| Workers affected | 500 | 300 | +200 | 310 | +61% | 2000 | 1800 |" in md
    assert "## Where this sector is shedding jobs — by state" in md
    assert "| California | 5 | 400 | 100 | +300 | +300% |" in md
    assert "## Subsector detail — 3-digit NAICS" in md
    assert "| 2026-06 | 6 | 300 | 0 |" in md
    assert "| Food Manufacturing | 4 | 300 | 150 | +150 | +100% |" in md
    assert "Narrative generated by gpt-oss:20b" in md


def test_render_industry_insufficient_data():
    md = render_industry_report(
        _sector_agg(cur_notices=1, prior_notices=1),
        None,
        narrative_status="insufficient_data",
    )
    assert "**Score: N/A — insufficient data**" in md
    assert "Insufficient NAICS-enriched WARN activity in Manufacturing" in md


def test_render_industry_llm_unavailable_and_skipped():
    md = render_industry_report(_sector_agg(), None, narrative_status="llm_unavailable")
    assert "Narrative unavailable this week" in md
    md = render_industry_report(_sector_agg(), None, narrative_status="skipped")
    assert "Narrative generation was skipped" in md


def test_render_industry_escapes_scraped_state_names():
    md = render_industry_report(
        _sector_agg(
            states=[
                DeltaRow(
                    key="XX", name="Weird | <State>",
                    cur_notices=1, cur_layoffs=10, prior_notices=0, prior_layoffs=0,
                ),
            ],
        ),
        None,
        narrative_status="skipped",
    )
    assert "| Weird \\| &lt;State&gt; | 1 | 10 |" in md


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------

def test_table_cells_escape_scraped_strings():
    md = render_report(
        _agg(
            counties=[
                DeltaRow(
                    key="Weird | <County>", name="Weird | <County>",
                    cur_notices=1, cur_layoffs=10, prior_notices=0, prior_layoffs=0,
                ),
            ],
        ),
        None,
        narrative_status="skipped",
    )
    assert "| Weird \\| &lt;County&gt; | 1 | 10 |" in md


def test_write_report_atomic(tmp_path):
    path = write_report(tmp_path / "reports", "CA", "# hello\n")
    assert path == tmp_path / "reports" / "CA.md"
    assert path.read_text(encoding="utf-8") == "# hello\n"
    assert list(path.parent.glob("*.tmp")) == []

    write_report(tmp_path / "reports", "CA", "# replaced\n")
    assert path.read_text(encoding="utf-8") == "# replaced\n"

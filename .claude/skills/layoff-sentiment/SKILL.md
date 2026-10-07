---
name: layoff-sentiment
description: Write the WARN Index layoff sentiment reports (per state, national, per NAICS industry) from the weekly prod payloads, validate them, and open a PR
argument-hint: "[all | XX ... | US | industry <sector> ...]  (default: all 72)"
---

# Write the layoff sentiment reports

The site's report pages (state pages, `/reports`, `/reports/industry/<sector>`)
serve markdown committed to `warn_v2/reports/published/`:

- `{CODE}.md`: one per state (51 codes, `warn_v2/states.py` `STATE_NAMES`)
- `US.md`: the national roll-up
- `industry_{sector}.md`: one per NAICS sector (20, `warn_v2/companies/naics.py`
  `NAICS_SECTORS`; ids like `31-33`)

You write those files from the figures the weekly `sentiment-report` CronJob
exports (`payloads.json`, Mon 02:07 UTC). Every number you write comes from
that payload. You add the judgment: what moved, where, and whether it matters.

**Done means ALL of these hold:**
1. Every targeted file was rewritten from the current payload.
2. `python .claude/skills/layoff-sentiment/validate.py <payloads.json>` exits 0
   over **every** file in `warn_v2/reports/published/`, not just the ones you
   touched.
3. A PR is open with the changes, and it was not merged. Merging is a prod deploy.

## Setup

- Work in a git worktree or a fresh branch off `origin/main`, named
  `claude/layoff-sentiment-<as_of>`. Never commit on `main`.
- Before you start, check for an already-open sentiment PR. Use
  `gh pr list --state open --json number,title,headRefName` and filter the
  titles client-side; `--search` silently returns `[]` with this token. If one
  is open, stop and report it rather than opening a duplicate.
- gh auth for this shell:
  `export GH_TOKEN=$(printf 'protocol=https\nhost=github.com\n' | git credential fill | sed -n 's/^password=//p')`

## Step 1: Fetch the payloads

```bash
curl -sS -D "$SCRATCH/headers.txt" -o "$SCRATCH/payloads.json" https://warnindex.com/api/reports/payloads
```

- `content-type` in the headers **must** be `application/json`. An unknown
  `/api` path returns the SPA's HTML shell with HTTP 200, so a 200 status
  proves nothing. If you get a 404 JSON error, the cron hasn't written the file
  yet: stop and report.
- Check `schema == 1`, and note `as_of`. If `as_of` is more than 8 days old the
  weekly cron is stale. Say so in the summary, but still write the reports.

Payload shape: `{"schema", "as_of", "jurisdictions": {CODE: …}, "industries": {sector: …}}`.
Each entry has:
- `current_window`, `prior_window`, `same_window_last_year`: the dates, plus
  notices/layoffs for last year's window.
- `totals`.
- `year_over_year`: trailing 12 months vs the 12 months before.
- `pct_change`: pre-computed. A null means the earlier figure was 0.
- `sufficient`: whether the windows hold 5 or more notices.
- `monthly`: 12 rows, each with `layoffs_year_earlier`.
- Jurisdictions only: `top_counties` (`top_states` for US), `top_sectors`,
  `naics_coverage_pct`, and an optional `forecast`.
- Industries only: `score`, `grade`, `top_states`, `top_subsectors`,
  `coverage_note`.
- Optional `bls_context` (US and industries): BLS payroll changes in
  thousands, plus the unemployment rate for US.
- Each top row has: `name`, `notices_current`, `layoffs_current`,
  `notices_prior`, `layoffs_prior`, `delta_layoffs`, `pct_change`.

## Step 2: Pick the targets

From `$ARGUMENTS`: nothing or `all` means all 72. `XX` is a state, `US` is
national, and `industry 31-33` is a sector. Several can be given.

## Step 3: Write the reports

For a full run, fan out to subagents: about 6 batches of 12, each in the
background, then wait for all of them. Give every subagent:
- the absolute path of this SKILL.md, and tell it to follow **Writing rules**
  and **Templates** exactly;
- the absolute path of `payloads.json`;
- its list of targets.

Each subagent writes its files, runs the validator on just those files, and
fixes them until they pass. For a handful of targets, write them yourself.

### Writing rules (these are hard rules)

- **Numbers.** Use ONLY numbers and dates present in that entity's payload.
  Never compute, sum, subtract, extrapolate, or round into a new figure. Copy
  percentages only from `pct_change` fields. The validator rejects any number
  it can't find in the payload. The fixed constants are allowed (90-day
  windows, 12 months, 6-month outlook, 80% band, the score formula). You may
  add thousands separators (`1,234`).
- **Null percentages.** A null `pct_change` means the earlier figure was 0.
  Write "no comparable activity was recorded" in prose, and `new` in tables
  (or `—` when both figures are 0). Never call it a rise.
- **Job losses.** Every layoff figure counts workers losing their jobs. A rise
  is bad news ("worsened", "climbed", "rose", "increased"). A fall is relief
  ("eased", "declined", "fell", "improved").
- **Banned words.** "add", "added", "grow", "grew", "gain", "gained" (and
  their other forms) are banned everywhere, even when talking about job
  losses. Write "job losses rose to 262 from 114".
- **Both comparisons.** The headline cites the prior window (momentum) and the
  same window last year (seasonal). If they point different ways, say so
  plainly. Use the trailing-12-month totals for the long-run picture.
- **BLS.** Use `bls_context` only when it's present, in one attributed
  sentence ("BLS reports…"): whether payrolls rose or fell over the months
  covered, plus the unemployment rate for US. For industries, name the BLS
  industry as given; it can be broader than the NAICS sector. Never combine,
  net, or compare BLS figures arithmetically with WARN figures.
- **Forecast.** Use it only when `forecast` is present, and attribute it to
  the model ("the model projects…"). Cite only its own numbers, always with
  their lo–hi range, and never present them as recorded data.
- **Coverage.** If `naics_coverage_pct` is below 50, say that the industry
  figures cover only a minority of notices. Industry reports always note that
  their figures cover only NAICS-enriched notices and are directional.
- **Partial month.** The `monthly` row for `as_of`'s own month is partial:
  it holds only the days so far. Never read it as a trend or compare it with
  its `layoffs_year_earlier`. Say it is partial if you mention it.
- **Reporting lag.** States post WARN notices late, so the last weeks of the
  current window tend to be revised upward. When a sharp drop against the
  prior window drives the headline, add one neutral sentence saying recent
  weeks may rise as late filings arrive. That is a data caveat, not a cause.
- **Facts.** Never invent causes, companies, or events that aren't in the
  payload. Don't speculate about why something moved.
- **Tone.** Neutral and analytical: an economic bulletin, not news copy.
- **Markdown subset.** Use only what the SPA's renderer
  (`frontend/src/components/ReportMarkdown.tsx`) supports:
  - `#` and `##` headings
  - pipe tables with a `---` row (`---:` for right-aligned numbers)
  - whole-line `_italic_`
  - `-` bullet lists, one level only
  - `>` quotes
  - inline `**bold**`
  - `---` rules

  It does not render links, `*single*` italics, backticks, `###` headings,
  numbered or nested lists, or HTML. Escape a literal `|` inside a table cell
  as `\|`.
- **Insufficient data.** When `sufficient` is false, the `## Sentiment`
  section is a single sentence: "Insufficient recent WARN activity in {name}
  to support a trend narrative ({notices_current} notices in the current
  window, {notices_prior} in the prior)." Skip `## Analysis`. Keep the tables.

### Templates

Placeholders in `{}` are payload fields. Omit a section whose source rows are
empty, except Summary, Sentiment and Monthly trend, which are always present.

**State and US** (`{CODE}.md`, `US.md`):

```markdown
# {state_name} ({state}) — WARN Layoff Trends

_Generated {as_of} · Current window {current_window.start} → {current_window.end} vs prior {prior_window.start} → {prior_window.end} · same window last year {same_window_last_year.start} → {same_window_last_year.end}_

## Summary

| Metric | Current 90d | Prior 90d | Same 90d last yr | Trailing 12mo | Prior 12mo |
|---|---:|---:|---:|---:|---:|
| Notices | {totals.notices_current} | {totals.notices_prior} | {same_window_last_year.notices} | {year_over_year.notices_trailing_12mo} | {year_over_year.notices_prior_12mo} |
| Workers affected | {totals.layoffs_current} | {totals.layoffs_prior} | {same_window_last_year.layoffs} | {year_over_year.layoffs_trailing_12mo} | {year_over_year.layoffs_prior_12mo} |

**Job losses vs prior window: {pct} · vs same window last year: {pct} · trailing 12 months vs prior 12: {pct}**

## Sentiment

{At most 250 words of plain prose in three short movements: (1) the headline, using both
comparisons plus the 12-month picture; (2) geography: at most three counties (states for US)
where losses are concentrated, rising, or easing; (3) industry: at most three sectors. Then
the BLS sentence (US only, if present) and one or two forecast sentences (if present).}

## Analysis

{Optional, about 150–300 words. What is worth watching: divergence between momentum and
the seasonal comparison, concentration in one area or sector, the monthly path versus the
same month last year, how wide the forecast band is. Short paragraphs, and a `-` list of
two to four "what to watch" items if useful. All the same rules apply.}

## Where layoffs are shifting — by county        ← "by state" for US

| County | Notices | Workers affected | Prior workers | Δ workers | Δ% |
|---|---:|---:|---:|---:|---:|
{one row per top_counties (top_states for US) entry: name, notices_current, layoffs_current,
layoffs_prior, delta_layoffs with a sign (+12 / -8 / 0), pct_change + "%" or new/—}

## Industry pressure — NAICS sectors

{the same table built from top_sectors, with a "Sector" column}

_NAICS coverage: {naics_coverage_pct}% of current-window notices have an enriched company._

## Monthly trend (last 12 months)

| Month | Notices | Workers affected | Same month last yr |
|---|---:|---:|---:|
{one row per monthly entry}

## Outlook — next 6 months (model estimate)       ← only when forecast is present

| Month | Notices (80% band) | Workers affected (80% band) |
|---|---:|---:|
{per forecast.points entry: "{notices} ({notices_lo}–{notices_hi})", "{layoffs} ({layoffs_lo}–{layoffs_hi})"}

_Statistical projection ({forecast.model}, fit on {forecast.history_months} months of history through {forecast.last_history_month}); not recorded data._

---

_Figures computed from non-superseded WARN notices bucketed by notice date; notices without a reported worker count contribute 0 to the workers-affected sums. Written analysis by Claude from the {as_of} figures._
```

**Industry** (`industry_{sector}.md`): the same structure, with these changes:
- H1 is `# {sector_name} (NAICS {sector}) — Industry Scorecard`.
- Insert this right after the `_Generated` line:

  ```markdown
  ## Scorecard

  **Score: {score}/100 — Grade {grade} ({label})**

  _How this score works: 50% 90-day layoff momentum, 30% year-over-year trend, 20% notice momentum — each measured against this sector's own recent baseline. Higher is healthier: A = layoffs easing sharply, F = surging._

  > {coverage_note}
  ```

  Grade labels: A easing sharply, B easing, C stable, D elevated, F surging.
  When `score` is null, write `**Score: N/A — insufficient data**`.
- Geography: `## Where this sector is shedding jobs — by state`, built from
  `top_states`.
- Industry detail: `## Subsector detail — 3-digit NAICS`, built from
  `top_subsectors`, with no coverage line.
- No Outlook section. Industries have no forecast.
- Footer:
  `_Figures computed from non-superseded, NAICS-enriched WARN notices bucketed by notice date; notices without a reported worker count contribute 0 to the workers-affected sums. Written analysis by Claude from the {as_of} figures._`

## Step 4: Validate (the gate)

```bash
python .claude/skills/layoff-sentiment/validate.py "$SCRATCH/payloads.json"
```

Stdlib only, so any Python 3.11+ works. Run it from the repo root. Fix every
line it prints, then re-run until it reports `failed=0`. Never weaken the
validator to get a report through. If a check is genuinely wrong, say so in
the PR and fix the check in its own commit.

Then read three reports in full yourself: `US.md`, the state with the biggest
`totals.layoffs_current`, and the industry with the lowest `score`. Check that
the prose reads well and that the direction words match the numbers. The
validator checks that numbers exist, not that "rose" was really a rise.

## Step 5: Open a PR (never merge)

```bash
git add warn_v2/reports/published
git commit -m "docs(reports): layoff sentiment reports for {as_of}"
git push -u origin HEAD
gh pr create --base main --title "docs(reports): layoff sentiment reports for {as_of}" --body-file <file>
```

The PR body covers: `as_of`; the counts (written, insufficient); the three
biggest national movers in a sentence each; anything odd (a stale cron, a
missing BLS block). End it with the attribution line from the session's
system reminder.

Merging deploys the reports. They ship inside the image, and the API serves
them as-is. `docker.yml` normally skips `**.md` changes but re-includes
`warn_v2/reports/published/**`, so a report-only PR still builds. Keep that
filter if you ever touch it.

## Step 6: Summarize

Report the PR link, `as_of`, the counts, and any check you could not satisfy.

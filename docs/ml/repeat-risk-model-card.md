# Model card: repeat-layoff risk

**Question.** An employer has just filed a WARN notice. What is the
probability that it files another one 1 to 12 months from now?

**Status.** Offline study. Nothing in production reads this model yet. The plan from here:

1. A weekly train-and-score CronJob running in shadow mode.
2. Once a few shadow runs have been reviewed, scores exposed on company pages.

Code is in `warn_v2/ml/`. Reproduce the results with:

```
warn-v2 ml-backtest --from-jsonl notices.jsonl --out out/ --as-of 2026-10-12
```

Drop `--from-jsonl` to read from the database instead.

## Why this target

A WARN notice means jobs are lost now. A *second* notice within a year is the
pattern job seekers and local workforce boards care about most: a company still
shedding staff, or a closure rolling site by site. The question is answerable
from public data alone. It also produces calibrated probabilities that a product
can show honestly as tiers.

## Definition

| | |
|---|---|
| Unit | Employer **event**, not notice. One reduction in force is often filed as many notices (one per site, one per state, amendments). Per company, an event opens at its first notice (t0). Notices in the next 30 days belong to that event. The next notice after those 30 days opens a new event. |
| Company | `COALESCE(canonical_company_id, company_id)`, after the nightly consolidator's merges. Unlinked notices fall back to the normalized employer name. |
| Prediction time | t0. Features read only notices dated on or before t0. Same-day multi-site filings count as known at t0. |
| Label | The next event starts within (t0 + 30 d, t0 + 365 d]. |
| Censoring | An event gets a label only once its full 365 days have passed **and** its state's coverage counts as real data for every month in that window. A scraper hole would otherwise read as "never filed again" and plant false negatives. Coverage holes come from the Poisson mask in `warn_v2/outlook/coverage.py`. A Kaplan-Meier curve over all events cross-checks the labelled base rate. |
| Exclusions | Superseded rows, MS "Non-WARN" rows, SC 2013-2021 (dates there are year-only placeholders), and undated notices. Counts of 0 or below, or above 50,000, are treated as missing. |

### Features (all known at t0)

- **The filing itself:** notices and states filed on t0; log of affected workers (with a flag when no count was given); closure share; notice-to-effective lead time (with a flag when it equals the imputed 60-day default).
- **Company history:** notices in the prior 1 and 3 years; number of prior events; days since the previous notice; prior affected workers; distinct prior states.
- **Context:** the state (categorical); how many years the state has been covered (left truncation: a "first-time filer" in a newly covered state may simply be unobserved); the state's and the nation's filing pace over the trailing 90 days; month of the year.

**Deliberately excluded:**

- **Enrichment fields** (NAICS, employee count, corporate parent). They are present-day snapshots, not point-in-time values: a company's current headcount already reflects the layoffs being predicted. Some of them are also provider-licensed.
- **BLS series.** They would need publication-lag alignment, and the regional pace features carry most of the same macro signal. Both groups are candidates for an ablation study.

## Evaluation design

- **Rolling origin.** For each test year Y:
  - train on events whose label was already known on January 1 of Y (t0 + 365 d < Y);
  - test on the labelled events that open in Y.
  - Test years never overlap, and no fold sees an outcome from its own future.
- **Candidates:**
  - base rate (the floor);
  - **"filed in the last 3 years"**, the first rule an analyst would write by hand;
  - **"count of prior events"**, the strongest hand rule found, and the real bar to clear;
  - L2 logistic regression;
  - HistGradientBoosting.
  - Hyperparameters are fixed and untuned, so no model was tuned on test years.
- **Calibration.** Platt scaling, fitted on the most recent training year by a model that never saw that year.
  - Isotonic was tried first. Its step function ties scores and lost about 0.05 PR-AUC in ranking, so it was dropped.
- **Metrics.**
  - Primary: PR-AUC, since positives are about 20%.
  - Also reported: ROC-AUC, precision at the top 10%, Brier score, and ECE over equal-frequency deciles.
  - Results are pooled across folds, both with and without 2020, a regime of its own.
  - 95% confidence intervals come from a **company-clustered bootstrap**. Events from one employer are correlated, so an event-level bootstrap would overstate certainty.
- **Model choice.** Logistic regression unless gradient boosting's PR-AUC advantage has a confidence interval that excludes zero: the simpler model wins ties.

## Results

Snapshot of the public API taken 2026-10-12: 85,562 notices → 41,862 companies → 62,040 events, of which 54,932 are labelled. Prevalence is 0.200, and the Kaplan-Meier 365-day repeat rate is also 0.200. There are 15 test years, 2010 to 2024. The full report, with per-fold and per-slice tables, is [repeat-risk-backtest-2026-10-12.md](repeat-risk-backtest-2026-10-12.md).

| model | PR-AUC (95% CI) | PR-AUC ex-2020 | ROC-AUC | P@10% | ECE |
|---|---|---|---|---|---|
| base rate | 0.173 | 0.216 | — | 0.197 | 0.046 |
| filed in last 3 years | 0.524 (0.476 to 0.565) | 0.580 | 0.759 | 0.709 | — |
| count of prior events | 0.568 (0.523 to 0.607) | 0.620 | 0.787 | 0.709 | — |
| logistic regression | 0.582 (0.536 to 0.620) | 0.639 | 0.782 | 0.699 | 0.022 |
| **gradient boosting** | **0.601 (0.557 to 0.638)** | **0.647** | 0.805 | 0.715 | **0.011** |

- **Model choice:** gradient boosting minus logistic regression is +0.019 PR-AUC [+0.014, +0.025], so the rule picks gradient boosting. It ties or wins in 14 of 15 years, and most of the margin comes from 2020.
- **Where the signal is:** almost all of it is in company history. `prior_events` alone is worth ΔPR-AUC 0.24, which is why the "count of prior events" rule is the real competitor. The model's lift over it is modest but clear: +0.033 PR-AUC [+0.027, +0.040].
- **First-time filers:** the model is near chance for them (PR-AUC 0.107 against prevalence 0.079), and they are about two thirds of events. **The product should show "not enough history" for them rather than a score.**
- **Calibration:** after Platt scaling it holds across deciles, from 0.04 to 0.71 predicted against 0.05 to 0.70 observed.
- **A bug the backtest caught:** in a leap-year fold, the calibration set had shrunk to the filings from one day. The fix is in `fit()`, and a regression test covers it.

## Known limitations

- **Notice date is not arrival date.** Historical backfills were scraped years after the fact, so "dated on or before t0" is the best available point-in-time proxy. It is not a replay of what was known on t0.
- **Entity resolution uses hindsight.** `canonical_company_id` is today's merge graph. A company's early notices may only be linked because of names seen later, which slightly inflates the history features.
- **One state's coverage gates each label.** An employer that files again in a state with a coverage hole may be recorded as a negative.
- **State mix.** CA alone is about a quarter of all events, and the per-state slices show where the model is weaker.
- **Regime shift.** 2020 is a different world: high volume and low repeat rate. Calibration fitted on the year before or after it drifts.
- **Scope of use.** These are statements about historical filing patterns, not forecasts of any company's decisions. Show them as risk tiers with this card linked, never as a verdict on a named employer.

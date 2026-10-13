# Model card: repeat-layoff risk

**Question.** An employer has just filed a WARN notice. What is the
probability that it files another one 1 to 12 months from now?

**Status.** Shadow mode. A weekly CronJob (`warn-v2 ml-train`) trains and scores. The company-page card ships dark behind `repeatRisk.public`: it is verified on staging first, and turned on in prod once the shadow runs have been reviewed.

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

- **The filing itself:** notices and states filed on t0; log of affected workers (0 when no count was given, since valid counts are positive); closure share; notice-to-effective lead time (with a flag when it equals the imputed 60-day default).
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
- **Model choice.** Logistic regression unless gradient boosting's PR-AUC advantage has a confidence interval that excludes zero both pooled *and* without 2020: the simpler model wins ties, and one atypical year can't decide.
- **GBM settings.** A fixed 150 iterations with no built-in early stopping. sklearn's early stopping holds out a *random* 10%, which shares companies with the training rows and would stop optimistically.

## Results

Snapshot of the public API taken 2026-10-12: 85,562 notices → 41,862 companies → 62,040 events, of which 54,932 are labelled. Prevalence is 0.200, and the Kaplan-Meier 365-day repeat rate is also 0.200. There are 15 test years, 2010 to 2024. The full report, with per-fold and per-slice tables, is [repeat-risk-backtest-2026-10-12.md](repeat-risk-backtest-2026-10-12.md).

| model | PR-AUC (95% CI) | PR-AUC ex-2020 | ROC-AUC | P@10% | ECE |
|---|---|---|---|---|---|
| base rate | 0.173 | 0.216 | — | 0.197 | 0.046 |
| filed in last 3 years | 0.524 (0.476 to 0.565) | 0.580 | 0.759 | 0.709 | — |
| count of prior events | 0.568 (0.523 to 0.607) | 0.620 | 0.787 | 0.709 | — |
| logistic regression | 0.576 (0.530 to 0.617) | 0.631 | 0.782 | 0.694 | 0.022 |
| **gradient boosting** | **0.594 (0.550 to 0.632)** | **0.644** | 0.799 | 0.711 | **0.014** |

- **Model choice:** gradient boosting minus logistic regression is +0.018 PR-AUC [+0.013, +0.025] pooled and +0.013 [+0.007, +0.019] without 2020. Both intervals exclude zero, so the rule picks gradient boosting.
- **Where the signal is:** almost all of it is in company history. `prior_events` alone is worth ΔPR-AUC 0.24, which is why the "count of prior events" rule is the real competitor. The model's lift over it is modest but clear: +0.027 PR-AUC [+0.021, +0.034].
- **First-time filers:** the model is near chance for them (PR-AUC 0.111 against prevalence 0.079), and they are about two thirds of events. **The product should show "not enough history" for them rather than a score.**
- **Calibration:** after Platt scaling it holds across deciles, from 0.04 to 0.73 predicted against 0.06 to 0.71 observed. The top deciles run slightly hot, by about 0.02.
- **A bug the backtest caught:** in a leap-year fold, the calibration set had shrunk to the filings from one day. The fix is in `fit()`, and a regression test covers it.

## Operation (shadow mode)

The weekly run (`warn_v2/ml/train.py`, chart value `mlTrain`, Sundays 05:41, after the consolidator):

1. Rebuilds the dataset and reruns the backtest. The report is written to `<reports>/repeat_risk_backtest.{json,md}`.
2. Fits the chosen algorithm on every labelled event: the **challenger**. It is saved to `<reports>/models/repeat_risk/<version>/` along with its backtest and metadata.
3. **Promotes** it only if all three gates pass on the latest test year:
   - ECE ≤ 0.05;
   - PR-AUC at or above the prior-events rule's;
   - when the champion was graded on the same year, PR-AUC no more than 0.02 below the champion's.

   Otherwise the previous champion keeps scoring. A champion whose artifact can't be read is replaced.
4. **Scores** every event whose horizon is still open with the champion, into `repeat_risk_scores`. Features are fixed at t0, so a version scores each event only once.
5. **Records monitoring** on the `ml_model_runs` row, exported as `warn_ml_*` gauges by the DB-backed collector:
   - the challenger's backtest PR-AUC and ECE;
   - **PSI** of today's scores against the champion's own backtest scores (above 0.25 means the inputs moved);
   - **realized PR-AUC**: each event's *first* score, graded once its horizon has closed and its label is in. It stays empty until scores are a year old.

## How it is shown

`GET /api/companies/{id}/repeat-risk` (and a "Repeat-filing risk" card on the company page) returns the champion's score for the employer's latest filing whose 12-month window is still open. It 404s while `repeatRisk.public` is off.

- **Prior filers** get a tier from the calibrated probability: low below 0.15, moderate below 0.35, high at 0.35 and above. The base rate is about 0.20. The card shows the percentage next to that base rate.
- **First-time filers** get `insufficient_history` and **no number**. The backtest puts the model near chance for them, so a score would be false precision.
- **No open filing** (the last one is over a year old): nothing is shown.
- `GET /api/reports/repeat-risk` serves the headline backtest numbers from the latest weekly run.

## Known limitations

- **Notice date is not arrival date.** Historical backfills were scraped years after the fact, so "dated on or before t0" is the best available point-in-time proxy. It is not a replay of what was known on t0.
- **Entity resolution uses hindsight.** `canonical_company_id` is today's merge graph. A company's early notices may only be linked because of names seen later, which slightly inflates the history features.
- **One state's coverage gates each label.** An employer that files again in a state with a coverage hole may be recorded as a negative.
- **State mix.** CA alone is about a quarter of all events, and the per-state slices show where the model is weaker.
- **Calibrator/model mismatch.** Platt is fitted on a probe model that hasn't seen the last 365 days, then applied to the model refitted on everything. Out-of-fold ECE is small (0.014), but the gap sits exactly on the most recent year. The production job (PR 2) should measure this directly.
- **Regime shift.** 2020 is a different world: high volume and low repeat rate. Calibration fitted on the year before or after it drifts.
- **Scope of use.** These are statements about historical filing patterns, not forecasts of any company's decisions. Show them as risk tiers with this card linked, never as a verdict on a named employer.

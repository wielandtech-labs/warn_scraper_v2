# ML hand-off — 2026-10-13

This picks up after the repeat-layoff risk launch. Since then, two follow-on ML projects have been built: a **discrete-time survival challenger** for repeat risk, and **learned entity resolution (ER)** for `Company` rows. All the code is merged. What's left is the real-data part: in-cluster Jobs have been launched, and their outputs still need to be read, labelled and written up.

Read these alongside this note:
- the repo `CLAUDE.md`;
- [ml/repeat-risk-model-card.md](ml/repeat-risk-model-card.md) (it has a "Challenger" section for the survival model);
- [ml/entity-resolution-model-card.md](ml/entity-resolution-model-card.md).

## What shipped

| PR | What | State |
|---|---|---|
| w_homelab#1128 | `repeatRisk.public: true` in prod. The repeat-filing risk card is live on company pages. | merged |
| warn_scraper_v2#361 | Survival challenger: `ml/survival.py`, `ml-survival-backtest`, `followup_days` in events, IPCW Brier/IBS and Uno's C | merged |
| warn_scraper_v2#362 | ER stages A1 and A2: `ml/er/` (profiles, blocking, features, weak labels, matcher, clustering, evaluation), `ml-er-sample`, `ml-er-eval`; the consolidator grouping extracted into `heuristic_merge_map` | merged |
| warn_scraper_v2#365 | ER stage A3: the `company_merge_suggestions` table (migration `0a5fbf79b129`), `ml-er-suggest`, admin queue API and UI, admin decisions as feedback labels, `--er-keys` on both backtests | merged |
| w_homelab#1130 | One-off Job `warn-v2-ml-survival-backtest-20261013` | merged, Job ran |
| w_homelab#1131 | `warn-v2-grant-warn-ml-ro-er-20261013` (adds `company_merge_overrides` to `warn_ml_ro`) and `warn-v2-ml-er-sample-20261013` | merged, Jobs ran |

**Nothing auto-merges companies.** `canonical_company_id` only changes when an admin clicks Accept in the suggestions queue, and the queue stays empty until someone runs `ml-er-suggest`.

## Waiting on Raphael (blocking the next steps)

1. **Survival backtest output.**
   ```
   kubectl -n warn-v2 logs job/warn-v2-ml-survival-backtest-20261013
   ```
   The report has also been written to the reports PVC as `repeat_risk_survival.{json,md}`. Its numbers go into the "Challenger → Results" section of the repeat-risk model card.
   - **Adopt rule:** the hazard GBM's PR-AUC must not be significantly worse than the classifier's (the company-clustered 95% CI of the gap reaches 0), **and** its 365-day IPCW Brier score must be lower.
   - If it isn't adopted, the 90/180-day curves are the survival model's only product use.
2. **ER gold candidates.**
   ```
   kubectl -n warn-v2 logs job/warn-v2-ml-er-sample-20261013 | sed -n '/^a_id,/,$p' > gold_candidates.csv
   ```
   The Job has `backoffLimit: 2`, because it may have raced the grant Job. If the pod failed for good, check `kubectl describe job`. A permission error on `company_merge_overrides` means the grant never landed.

## Next steps, in order

1. **Label the gold set** (the agreed protocol: Claude pre-labels, a human audits).
   - Fill `same` (1/0/?) and `reason` for every row. Work only in the session scratchpad and **never commit the file**: it pairs real employer names with judgements.
   - "Same" means the same legal employer. Subsidiaries, franchisees and divisions count as **different**; corporate-family rollup is `parent_group_key`'s job.
   - Hand Raphael a random list of about 100 row numbers to audit. Record the agreement rate for the model card.
   - The audited file goes back to the PVC as `er/gold.csv`.
2. **w_homelab PR with the eval Jobs.** Copy the pattern of the merged Jobs (pin the current `$imagepolicy` tag, use the reports PVC, `cat` the `.md` to the log, give every container resources, no TTL):
   - **Grant:** `company_merge_suggestions` goes on `warn_ml_ro`'s allowlist, making 11 tables. Re-run the grant Job from #1131 with the table added, and keep the exact-list assertion. Without it, `ml-er-eval` skips the admin-feedback section, and `--er-keys` ignores rejected pairs; both print a message rather than failing.
   - **`ml-er-eval`:** on `warn-ml-ro-db`. It reads `er/gold.csv` and writes `er/er_eval.{json,md}`, with aggregates only (a test enforces that no names appear).
   - **`ml-backtest --er-keys` and `ml-survival-backtest --er-keys`:** on `warn-ml-ro-db`. They write `repeat_risk_*_er.{json,md}`, the downstream proof for ER. Merges change the event sets, so compare the two runs side by side (PR-AUC with CIs, prevalence, share of first-time filers), not event by event.
3. **Docs PR.** Fill in the "Results" sections of both model cards from the reports above. ER's headline: B-cubed and pairwise F1 for `system` vs `heuristic`, split into enriched and unenriched pairs, plus blocking recall.
4. **Run suggestions only if ER earns it.** If `system` beats `heuristic` on the **unenriched** gold slice, add a one-off `ml-er-suggest` Job.
   - It needs **`warn-v2-db`** (read-write), because it writes `company_merge_suggestions`. Try `--dry-run` first.
   - Admins then work the queue at `/admin/companies`. Each decision feeds the next `ml-er-eval`.
5. **Prune** every finished one-off Job (survival backtest, grant, ER sample, and later the eval Jobs) in a follow-up w_homelab PR.
6. **Housekeeping.** A stray `claude/dreamy-wozniak-ekxiab` branch exists on w_homelab. Its tree is identical to main, and the session's git proxy couldn't delete it, so delete it on GitHub.

## Unknowns to watch on the real runs

- **ER at prod scale has never run.** It has been tested on synthetic data only: 3.7k rows and 85k candidate pairs took about 30 s. Prod has tens of thousands of `Company` rows. Feature building is pure Python per pair, and the sample Job's 4Gi / 5400 s limits are guesses. If it OOMs or times out:
  - tighten blocking (`K_NEIGHBOURS`, `RARE_DF`, `MAX_BLOCK` in `ml/er/blocking.py`);
  - or raise the limits.
- **Survival runtime.** It fits three survival models plus the classifier per fold, with person-period expansion (about 10× the rows). The Job has 3Gi and 5400 s. If it hits the deadline, run fewer folds with `--first-year`.
- **Weak-label coverage.** The weak labels exist only where both rows are enriched. If the prod report shows very few weak positives, the matcher is thin, and the gold set carries the evaluation.

## Lessons from this arc (read before touching the code)

- **pandas 3 turns `None` into `NaN`** in string columns. `x is None` checks silently pass NaN through. That broke the weak labels and the consolidator's `website_domain()`. `records.build_profiles` now normalizes the enrichment columns back to `None`; use `pd.isna` elsewhere.
- **Survival risk sets must not depend on the outcome.** Keeping a partly observed interval only when the event fell inside it inflated GBM hazards for the cohorts next to every fold cutoff (synthetic F(180) 0.81 against 0.44 observed). An interval now enters the risk set only when follow-up covers all of it.
- **IPCW Brier at the horizon.** Non-repeaters followed for the full year sit at exactly `time == 365` and are censored. Count them as event-free (`time >= tau`, weighted by G(τ−)), or Brier@365 rewards whichever model predicts higher.
- **ER label leakage.** No enrichment field is a feature (`features.INPUT_COLUMNS` is an allowlist, and a test scrambles every enrichment column). Cross-fitting folds are grouped by connected component. The heuristic baseline never sees admin overrides.
- **ER suggestions move whole groups.** Accepting writes an override on the group's root, so a group is only proposed when the model holds all of it. Rejections are cannot-links between whole groups. Accept refuses stale suggestions (409). Don't loosen any of these without re-reading the A3 review findings in #365.
- **Synthetic data can lie both ways.** One generator gave PR-AUC 1.0 (every entity had its own ZIP) and B-cubed 0.3 (400 names for 1,500 entities). Sanity-check synthetic numbers before trusting a pipeline change.
- **Git and Flux mechanics:**
  - After a squash merge, the session branch still holds pre-squash commits. Restart it from `origin/main` and force-with-lease; it holds only merged history.
  - The w_homelab clone is shallow and fetches only `main`. Set an upstream with `git fetch origin +refs/heads/<b>:refs/remotes/origin/<b>`, or the stop hook reports phantom unpushed commits.
  - An image tag appears in the HelmRelease about 5 minutes after a warn_scraper_v2 merge. Pin one-off Jobs to the tag from Flux's bump commit; never guess it.
  - A flux-local diff on a stale branch shows main's later image bumps as "reverts". A squash merge doesn't actually revert them, but merge main in for a clean render.
  - `pkill -f <pattern>` matches its own shell when the pattern sits in the same command line.

## Where things are

| Path | What |
|---|---|
| `warn_v2/ml/survival.py`, `survival_report.py` | Survival backtest and report |
| `warn_v2/ml/events.py` | `followup_days`; `load_notices(key_map=…)` for `--er-keys` |
| `warn_v2/ml/er/` | `records`, `blocking`, `features`, `labels`, `model`, `cluster`, `evaluate`, `run` (fit, eval, sample), `suggest`, `remap` |
| `warn_v2/scripts/consolidate_companies.py` | `heuristic_merge_map`, shared with the ER baseline |
| `warn_v2/api/routes/admin.py` | Merge-suggestion endpoints |
| `frontend/src/routes/admin-companies.tsx` | The "Suggested merges" panel |
| `tests/test_ml_survival.py`, `test_ml_er.py`, `test_ml_er_suggest.py`, `er_synthetic.py` | Tests and the synthetic ER generator |
| w_homelab `clusters/prod/apps/warn-v2/job-*-20261013.yaml` | This arc's one-off Jobs (to prune) |

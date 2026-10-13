# Model card: learned entity resolution

**Question.** Two `Company` rows: are they the same employer?

**Status.** Research. `warn-v2 ml-er-eval` measures the model against today's consolidator; nothing writes `canonical_company_id`. A later stage proposes merges to the admin merge UI, and an admin accepts or rejects each one.

Code is in `warn_v2/ml/er/`.

```
warn-v2 ml-er-sample --reports-dir /var/reports   # er/gold_candidates.csv, for labelling
warn-v2 ml-er-eval   --reports-dir /var/reports   # er/er_eval.{json,md}; uses er/gold.csv if present
```

Both read the database only. Run them in-cluster on the read-only `warn_ml_ro` role.

## Why

Every per-company number on the site depends on how notices are grouped into companies: rollups, the top-employers list, and above all the repeat-risk model. In that model, `prior_events` alone is worth ΔPR-AUC 0.24, and its card lists entity resolution as a known limitation.

The nightly consolidator (`warn_v2/scripts/consolidate_companies.py`) merges rows in two ways:
- they share a provider unique id;
- their normalized names are identical.

Both miss the common WARN case: an employer **without** a unique id whose filings spell it differently. For example, `KMART CORPORATION # 7435`, `Kmart Corp - Dover DC` and `K-Mart Corporation` are one employer, but the consolidator sees three.

## Pipeline

| step | module | what it does |
|---|---|---|
| Profiles | `records.py` | One per raw `Company` row: its name variants, plus what its notices say (states, cities, ZIPs, geocoded sites, filing dates, size). |
| Blocking | `blocking.py` | Union of three candidate generators: char-trigram TF-IDF k-NN on the name, first significant token × state, and shared rare tokens. Blocks over 100 rows are skipped. Reports pair completeness and reduction ratio. |
| Features | `features.py` | 21 pairwise features, symmetric in (a, b): name similarity (Jaro–Winkler, token-set, char/word TF-IDF cosine, dba cross-match, acronyms, conflicting store numbers, IDF of the rarest shared token, name frequency) and filing evidence (state Jaccard, shared city/ZIP, nearest sites in km, same-day filings in one state, date-range overlap and gap, sizes). |
| Labels | `labels.py` | Weak labels from enrichment. The same unique id is positive. Different ids are negative, unless the two rows also share the same normalized name *and* website (exactly the consolidator's Boeing exception). A shared website alone doesn't count, because subsidiaries list the parent's site and some rows carry a platform domain. Admin merge overrides are gold positives. |
| Matcher | `model.py` | HistGradientBoosting with fixed settings, cross-fitted with folds **grouped by connected component** of the positive weak-label graph. Platt calibration is fitted on the out-of-fold scores. Unlabelled pairs are scored by the average of the fold models, the same models the calibrator was fitted on, rather than by a model refitted on everything. |
| Clustering | `cluster.py` | Greedy **average linkage** (heap-driven) inside components of pairs scoring ≥ 0.2, merging while the average pair score is ≥ 0.5. Unscored pairs count as 0. Components over 2,000 rows fall back to single linkage at 0.5. Both honour cannot-links. Connected components at 0.5 is the baseline. |
| Evaluation | `evaluate.py` | Pairwise PR-AUC and P/R/F1, and B-cubed P/R/F1, each split into enriched pairs and the rest. |

### Leakage rules

- **No enrichment field is a feature.** That means unique id, website, parent ids, NAICS and headcount. The weak labels come from the same enrichment, so a model that saw them would learn the labeller instead of the employer. It would also be useless on the unenriched rows it exists for.
  - `features.INPUT_COLUMNS` is the allowlist of profile columns the features may read.
  - A test scrambles every enrichment column and checks that the features don't move.
- **Group folds.** If A=B and B=C are both labelled, a random split could train on A=B and test on B=C. The model would then score the test pair by recognising the company, not by matching evidence. Splitting by connected component keeps whole companies on one side.
- **The baseline doesn't see the gold.** The heuristic baseline replays the consolidator's own code (`heuristic_merge_map`, shared with production) *without* admin overrides, because overrides are gold labels.

### Two ways to cluster

- **model:** pair scores only. This is what the model knows from filings alone.
- **system:** pair scores plus unique-id agreement as must-link and disagreement as cannot-link, plus the admins' decisions.
  - A merge override is a must-link.
  - A keep-separate override cannot-links the company to every candidate partner, except rows an admin merged into it.
  - This is what would run in production, and it is the fair comparison with the heuristic, which also uses unique ids.
  - Because system mode takes overrides as input, override recall is reported only for the other clusterings.

## Evaluation and the gold set

Weak labels exist only where *both* rows are enriched. Those are mostly large, clean names, so weak-label metrics flatter the model on exactly the pairs where it matters least. The gold set fixes that:

1. `ml-er-sample` writes about 400 pairs to `<reports>/er/gold_candidates.csv`.
   - 90% are candidate pairs, stratified by model score band (0–0.1, 0.1–0.3, 0.3–0.7, 0.7–0.9, 0.9–1) × enriched/unenriched.
   - 10% are **pairs blocking dropped**, found by a looser trigram search (band `unblocked`). Without them, gold blocking recall would be 1 by construction. Pairs outside even the looser search stay invisible, so the reported figure is an upper bound.
   - Each row carries both names, states, cities, date ranges, notice counts and up to three addresses.
2. **Model-assisted labelling.** Claude pre-labels every pair `same` = 1, 0 or ? (skip), with a one-line reason. A human audits a random ~100 of them and corrects them. The agreement rate is reported here.
   - Disclosure: the labels are not fully independent of a model's judgement.
3. The labelled file goes back to `<reports>/er/gold.csv`. It never enters the repository, because it pairs real employer names with judgements. Only aggregate metrics leave the cluster.

## Results

Pending the first in-cluster run.

## Known limitations

- **"Same employer" is a judgement call.** Franchisees, subsidiaries and divisions sit between "same" and "different". The gold labels treat a different legal entity as different, and leave corporate-family rollup to `parent_group_key`.
- **Weak-label bias.** The training labels cover enriched pairs only. The unenriched slice of the gold set measures how well that transfers.
- **Gold set size.** About 400 pairs gives wide intervals, so read differences under ~0.05 F1 as ties.
- **Blocking ceiling.** A pair that blocking never proposes can't be merged. Blocking recall is reported against weak positives, admin overrides and gold positives.

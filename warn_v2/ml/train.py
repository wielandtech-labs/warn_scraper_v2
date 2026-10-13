"""Weekly train -> gate -> score for the repeat-layoff model (shadow mode).

One run:
1. rebuilds the events dataset and reruns the rolling-origin backtest;
2. fits the backtest's chosen algorithm on every labelled event (the
   challenger) and saves it under <reports>/models/repeat_risk/<version>/;
3. promotes it only if it passes the gates in ``decide`` — otherwise the
   previous champion keeps scoring;
4. scores every event whose horizon is still open with the champion;
5. records monitoring numbers on the run row: backtest PR-AUC/ECE, the PSI of
   today's scores against the champion's own backtest scores, and the
   realized PR-AUC of scores whose horizon has since closed.

Nothing user-facing reads the scores yet; that is the point of shadow mode.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.metrics import average_precision_score
from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from warn_v2.db.models import MlModelRun, RepeatRiskScore
from warn_v2.ml import MODEL
from warn_v2.ml.backtest import FittedModel, default_years, fit, run_backtest
from warn_v2.ml.events import FEATURES, HORIZON_DAYS, build_events, load_notices
from warn_v2.ml.report import build_report, render_markdown
from warn_v2.reports.generate import _atomic_write

log = logging.getLogger(__name__)

MAX_ECE = 0.05
# A challenger may trail the champion by this much on the same test year
# (bootstrap noise on one fold is about this size) and still replace it.
CHAMPION_TOLERANCE = 0.02
MIN_REALIZED = 200
PSI_BINS = 10


@dataclass
class FoldScore:
    year: int
    pr_auc: float
    ece: float
    rule_pr_auc: float  # the prior-events rule on the same fold
    pooled_ex_2020: float  # across all backtest years, for cross-year comparison


def latest_fold(report: dict[str, Any], algorithm: str) -> FoldScore:
    fold = report["folds"][-1]
    m = fold["models"]
    return FoldScore(
        year=fold["year"], pr_auc=m[algorithm]["pr_auc"], ece=m[algorithm]["ece"],
        rule_pr_auc=m["prior_events"]["pr_auc"],
        pooled_ex_2020=report["pooled_ex_2020"][algorithm]["pr_auc"],
    )


def decide(challenger: FoldScore, champion: FoldScore | None) -> tuple[bool, str]:
    """Promotion gates, cheapest objection first. Returns (promote, why)."""
    if challenger.ece > MAX_ECE:
        return False, f"ECE {challenger.ece:.3f} > {MAX_ECE} on {challenger.year}"
    if challenger.pr_auc < challenger.rule_pr_auc:
        return False, (
            f"PR-AUC {challenger.pr_auc:.3f} does not beat the prior-events rule "
            f"({challenger.rule_pr_auc:.3f}) on {challenger.year}"
        )
    if champion is None:
        return True, "no champion yet"
    if champion.year != challenger.year:
        # A new test year opened, so the latest-fold numbers aren't comparable.
        # Fall back to the pooled ex-2020 PR-AUC, which spans (nearly) the same
        # years for both.
        if challenger.pooled_ex_2020 < champion.pooled_ex_2020 - CHAMPION_TOLERANCE:
            return False, (
                f"pooled ex-2020 PR-AUC {challenger.pooled_ex_2020:.3f} trails champion "
                f"{champion.pooled_ex_2020:.3f} (new test year {challenger.year})"
            )
        return True, (
            f"new test year {challenger.year}; pooled ex-2020 PR-AUC "
            f"{challenger.pooled_ex_2020:.3f} vs champion {champion.pooled_ex_2020:.3f}"
        )
    if challenger.pr_auc < champion.pr_auc - CHAMPION_TOLERANCE:
        return False, (
            f"PR-AUC {challenger.pr_auc:.3f} trails champion {champion.pr_auc:.3f} "
            f"by more than {CHAMPION_TOLERANCE} on {challenger.year}"
        )
    return True, f"PR-AUC {challenger.pr_auc:.3f} vs champion {champion.pr_auc:.3f}"


def psi(reference: np.ndarray, current: np.ndarray, bins: int = PSI_BINS) -> float:
    """Population stability index of `current` against `reference`, over the
    reference's deciles. > 0.25 is the conventional "the inputs moved" line."""
    if len(reference) == 0 or len(current) == 0:
        return float("nan")
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    edges[0], edges[-1] = -np.inf, np.inf
    ref = np.histogram(reference, edges)[0] / len(reference)
    cur = np.histogram(current, edges)[0] / len(current)
    ref, cur = np.clip(ref, 1e-4, None), np.clip(cur, 1e-4, None)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def _company_id(key: str) -> int | None:
    return int(key[1:]) if key.startswith("c") and key[1:].isdigit() else None


def open_events(events: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """Events whose horizon hasn't closed — the ones a score is still about."""
    return events[events["t0"] + pd.Timedelta(days=HORIZON_DAYS) >= pd.Timestamp(as_of)]


def realized(session: Session, events: pd.DataFrame, as_of: date) -> dict[str, float]:
    """PR-AUC of the *first* score each now-labelled event received — what the
    model said back when it mattered, graded against what happened."""
    matured = as_of - timedelta(days=HORIZON_DAYS)
    rows = session.execute(
        select(RepeatRiskScore.company_key, RepeatRiskScore.event_start,
               RepeatRiskScore.score, RepeatRiskScore.scored_at)
        .where(RepeatRiskScore.event_start < matured)
    ).all()
    if not rows:
        return {"n": 0, "pr_auc": float("nan"), "prevalence": float("nan")}
    scores = (
        pd.DataFrame(rows, columns=["company_key", "t0", "score", "scored_at"])
        .sort_values("scored_at")
        .drop_duplicates(["company_key", "t0"])
        .assign(t0=lambda d: pd.to_datetime(d["t0"]))
    )
    lab = events.loc[events["labelled"], ["company_key", "t0", "label"]]
    graded = scores.merge(lab, on=["company_key", "t0"])
    n = len(graded)
    y = graded["label"].to_numpy(int)
    if n < MIN_REALIZED or y.min() == y.max():
        return {"n": n, "pr_auc": float("nan"),
                "prevalence": float(y.mean()) if n else float("nan")}
    return {"n": n, "pr_auc": float(average_precision_score(y, graded["score"])),
            "prevalence": float(y.mean())}


def _champion(session: Session) -> MlModelRun | None:
    return session.scalars(
        select(MlModelRun)
        .where(MlModelRun.model == MODEL, MlModelRun.promoted.is_(True))
        .order_by(MlModelRun.created_at.desc(), MlModelRun.id.desc())
        .limit(1)
    ).first()


def _load(run: MlModelRun) -> dict[str, Any] | None:
    """The champion's bundle, or None when it can't be used by this code:
    missing file, a pickle from another sklearn, or a different feature set
    (FittedModel predicts with this module's FEATURES)."""
    try:
        bundle: dict[str, Any] = joblib.load(Path(run.artifact_path) / "model.joblib")
    except Exception as exc:  # unpickling raises almost anything on skew
        log.warning("champion %s artifact unreadable (%s)", run.version, exc)
        return None
    if bundle.get("features") != FEATURES or bundle.get("sklearn") != sklearn.__version__:
        log.warning("champion %s was built for other features/sklearn", run.version)
        return None
    return bundle


def _json(obj: Any) -> str:
    """Strict JSON: NaN (nothing matured yet, no scores) becomes null."""

    def clean(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [clean(x) for x in v]
        if isinstance(v, float | np.floating):
            return None if math.isnan(v) else float(v)
        if isinstance(v, np.integer):
            return int(v)
        return v

    return json.dumps(clean(obj), indent=2, default=str, allow_nan=False)


def _prune(session: Session, keep_version: str) -> int:
    """Drop superseded scores: keep the current scorer's rows plus each
    event's first-ever score (what realized performance grades). Without
    this, weekly promotions would rescore every open event every week."""
    rows = session.execute(
        select(RepeatRiskScore.model_version, RepeatRiskScore.company_key,
               RepeatRiskScore.event_start, RepeatRiskScore.scored_at)
    ).all()
    first: dict[tuple[str, date], tuple[datetime, str]] = {}
    for v, k, t, at in rows:
        cur = first.get((k, t))
        if cur is None or (at, v) < cur:
            first[(k, t)] = (at, v)
    doomed = [
        (v, k, t) for v, k, t, _ in rows
        if v != keep_version and first[(k, t)][1] != v
    ]
    pk = tuple_(RepeatRiskScore.model_version, RepeatRiskScore.company_key,
                RepeatRiskScore.event_start)
    for i in range(0, len(doomed), 500):
        session.execute(delete(RepeatRiskScore).where(pk.in_(doomed[i:i + 500])))
    return len(doomed)


def train_and_score(
    session: Session,
    *,
    as_of: date,
    reports_dir: Path,
    code_version: str | None = None,
    years: list[int] | None = None,
    now: datetime | None = None,
) -> MlModelRun | None:
    """One weekly run. Returns the new run row, or None when the data can't
    support a backtest yet (e.g. a small staging database)."""
    now = now or datetime.now(UTC)
    notices = load_notices(session)
    events = build_events(notices, as_of=as_of)
    result = run_backtest(events, years or default_years(as_of))
    if not result.folds:
        log.warning("no backtest fold had enough data (%d events); nothing trained", len(events))
        return None
    report = build_report(notices, events, result, as_of=as_of)
    algorithm = report["chosen"]["model"]
    challenger_fold = latest_fold(report, algorithm)

    # Challenger: the chosen algorithm on every labelled event. Its PSI
    # reference is its own scores on its most recent labelled year, so PSI
    # measures input drift rather than the gap between two different models.
    labelled = events[events["labelled"]]
    challenger = fit(algorithm, labelled)
    recent = labelled[labelled["t0"] > labelled["t0"].max() - pd.Timedelta(days=HORIZON_DAYS)]
    reference = challenger.predict(recent)

    version = f"{now:%Y%m%dT%H%M%S}-{algorithm}"
    artifact_dir = reports_dir / "models" / MODEL / version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": challenger, "features": FEATURES, "sklearn": sklearn.__version__,
         "version": version, "reference_scores": reference},
        artifact_dir / "model.joblib",
    )

    champ_run = _champion(session)
    champ_bundle = _load(champ_run) if champ_run is not None else None
    champ_fold = (
        FoldScore(**json.loads(champ_run.metrics)["latest_fold"])
        if champ_run is not None and champ_bundle is not None else None
    )
    promote, why = decide(challenger_fold, champ_fold)
    if champ_run is not None and champ_bundle is None:
        why += f" (champion {champ_run.version} artifact unusable)"
    scorer: FittedModel | None = None
    scorer_version, scorer_reference = "", np.array([])
    if promote:
        scorer, scorer_version, scorer_reference = challenger, version, reference
    elif champ_bundle is not None and champ_run is not None:
        scorer = champ_bundle["model"]
        scorer_version = champ_run.version
        scorer_reference = champ_bundle["reference_scores"]

    # Score open events (features are fixed at t0, so a version scores each
    # event once; re-runs of the same champion only add new events).
    todo = open_events(events, as_of)
    n_new = n_pruned = 0
    current = np.array([])
    if scorer is not None and len(todo):
        current = scorer.predict(todo)
        done = set(session.execute(
            select(RepeatRiskScore.company_key, RepeatRiskScore.event_start)
            .where(RepeatRiskScore.model_version == scorer_version)
        ).all())
        new = [
            RepeatRiskScore(
                model_version=scorer_version, company_key=k, event_start=t.date(),
                company_id=_company_id(k), score=float(p), prior_events=int(n),
                scored_at=now,
            )
            for k, t, n, p in zip(
                todo["company_key"], todo["t0"], todo["prior_events"], current, strict=True
            )
            if (k, t.date()) not in done
        ]
        session.add_all(new)
        n_new = len(new)
        session.flush()
        n_pruned = _prune(session, scorer_version)

    metrics = {
        "latest_fold": vars(challenger_fold),
        "pooled": report["pooled"][algorithm],
        "pooled_ex_2020": report["pooled_ex_2020"][algorithm],
        "scorer_version": scorer_version,
        "open_events": len(todo),
        "scores_written": n_new,
        "scores_pruned": n_pruned,
        "score_psi": psi(scorer_reference, current),
        "realized": realized(session, events, as_of),
        "labelled_events": int(events["labelled"].sum()),
    }
    run = MlModelRun(
        model=MODEL, version=version, created_at=now, code_version=code_version,
        data_as_of=as_of, algorithm=algorithm, promoted=promote, decision=why,
        artifact_path=str(artifact_dir), metrics=_json(metrics),
    )
    session.add(run)
    session.flush()

    # Files last, so a run that fails above never replaces the published
    # report. Atomic, since the API serves the stable paths concurrently.
    _atomic_write(artifact_dir, "backtest.json", _json(report))
    _atomic_write(artifact_dir, "metadata.json", _json(
        {"version": version, "promoted": promote, "decision": why, **metrics}
    ))
    _atomic_write(reports_dir, "repeat_risk_backtest.json", _json(report))
    _atomic_write(reports_dir, "repeat_risk_backtest.md", render_markdown(report))
    return run

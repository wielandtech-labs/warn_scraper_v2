"""Pairwise features. Every one is symmetric in (a, b), and none reads an
enrichment column (records.ENRICHMENT_COLUMNS): see the module docstring there.

Name similarity:
- Jaro-Winkler and token-set ratio on the canonical name;
- TF-IDF cosine on its character trigrams and on its words;
- whether the canonical or the site-stripped name is identical;
- whether either name's trade name (dba) is the other's name;
- conflicting store or site numbers in the raw names;
- an acronym of one name equal to the other;
- the IDF of the rarest shared token, so a shared "Acme" outweighs a shared
  "Services";
- how common the more common of the two names is.

What the notices say:
- state overlap (Jaccard), and any shared city or ZIP;
- the closest pair of geocoded sites, in km;
- same-day filings in the same state, which is how one multi-site filing
  shows up under two spellings;
- overlap of the two filing date ranges;
- the gap between the two ranges;
- the smaller and larger notice count, and the ratio of total workers.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from warn_v2.ml.er.blocking import _tokens

FEATURES = [
    "name_jw", "name_token_set", "name_char_cos", "name_word_cos",
    "canonical_equal", "cleaned_equal", "dba_cross", "site_number_conflict",
    "acronym_match", "shared_token_max_idf", "name_freq_log",
    "state_jaccard", "shared_city", "shared_zip", "min_geo_km",
    "same_day_same_state", "date_overlap_frac", "date_gap_days_log",
    "notices_min_log", "notices_max_log", "layoff_ratio",
]

# Profile columns features.py may read. Anything else (above all the
# enrichment columns) is off limits; tests check this list against them.
INPUT_COLUMNS = ["name", "canonical", "cleaned", "dba", "states", "cities", "zips",
                 "points", "dates", "state_days", "n_notices", "total_layoffs"]

_NUMBER = re.compile(r"\d{2,}")
_EARTH_KM = 6371.0


def _site_numbers(name: str) -> frozenset[str]:
    return frozenset(_NUMBER.findall(name))


def _acronym(name: str) -> str:
    toks = _tokens(name)
    return "".join(t[0] for t in toks) if len(toks) >= 2 else ""


def _min_km(p: np.ndarray, q: np.ndarray) -> float:
    if not len(p) or not len(q):
        return math.nan
    lat1, lon1 = np.radians(p[:, 0])[:, None], np.radians(p[:, 1])[:, None]
    lat2, lon2 = np.radians(q[:, 0])[None, :], np.radians(q[:, 1])[None, :]
    h = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return float(2 * _EARTH_KM * np.arcsin(np.sqrt(np.clip(h, 0, 1))).min())


def _jaccard(x: frozenset, y: frozenset) -> float:
    u = len(x | y)
    return len(x & y) / u if u else math.nan


def _range_features(d1: np.ndarray, d2: np.ndarray) -> tuple[float, float]:
    """(overlap / shorter span, log1p of the gap in days between ranges)."""
    if not len(d1) or not len(d2):
        return math.nan, math.nan
    a0, a1 = d1[0], d1[-1]
    b0, b1 = d2[0], d2[-1]
    overlap = (min(a1, b1) - max(a0, b0)).astype(int)
    shorter = max(1, min((a1 - a0).astype(int), (b1 - b0).astype(int)) + 1)
    gap = max(0, -int(overlap))
    return max(0.0, (int(overlap) + 1) / shorter), math.log1p(gap)


def _rowwise_cos(X, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    Xn = normalize(X)
    return np.asarray(Xn[a].multiply(Xn[b]).sum(axis=1)).ravel()


def pair_features(profiles: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    """One row of FEATURES per pair (a, b are row positions in `profiles`)."""
    p = profiles[INPUT_COLUMNS]
    a = pairs["a"].to_numpy(int)
    b = pairs["b"].to_numpy(int)
    canon = p["canonical"].fillna("").to_numpy()

    char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3)).fit(canon)
    word_vec = TfidfVectorizer(analyzer=_tokens, min_df=1)
    try:
        W = word_vec.fit_transform(canon)
        idf = dict(zip(word_vec.get_feature_names_out(), word_vec.idf_, strict=True))
    except ValueError:  # no tokens at all (tiny fixtures)
        W, idf = None, {}
    char_cos = _rowwise_cos(char_vec.transform(canon), a, b) if len(a) else np.array([])
    word_cos = _rowwise_cos(W, a, b) if (W is not None and len(a)) else np.zeros(len(a))

    freq = p["cleaned"].map(p["cleaned"].value_counts()).to_numpy()
    acr = [_acronym(c) for c in canon]
    nums = [_site_numbers(n) for n in p["name"]]
    toks = [set(_tokens(c)) for c in canon]

    cleaned = p["cleaned"].fillna("").tolist()
    dba = p["dba"].fillna("").tolist()
    states, cities, zips = p["states"].tolist(), p["cities"].tolist(), p["zips"].tolist()
    points, dates, sdays = p["points"].tolist(), p["dates"].tolist(), p["state_days"].tolist()
    n_not, lay = p["n_notices"].tolist(), p["total_layoffs"].tolist()

    rows = []
    for k, (i, j) in enumerate(zip(a.tolist(), b.tolist(), strict=True)):
        ci, cj = canon[i], canon[j]
        shared = toks[i] & toks[j]
        ni, nj = nums[i], nums[j]
        overlap, gap = _range_features(dates[i], dates[j])
        li, lj = lay[i], lay[j]
        rows.append((
            JaroWinkler.normalized_similarity(ci, cj),
            fuzz.token_set_ratio(ci, cj) / 100.0,
            char_cos[k],
            word_cos[k],
            float(bool(ci) and ci == cj),
            float(bool(cleaned[i]) and cleaned[i] == cleaned[j]),
            float((bool(dba[i]) and dba[i] in (cj, cleaned[j]))
                  or (bool(dba[j]) and dba[j] in (ci, cleaned[i]))),
            float(bool(ni) and bool(nj) and not (ni & nj)),
            float((bool(acr[i]) and acr[i] == cj.replace(" ", ""))
                  or (bool(acr[j]) and acr[j] == ci.replace(" ", ""))),
            max((idf.get(t, 0.0) for t in shared), default=0.0),
            math.log(max(freq[i], freq[j])),
            _jaccard(states[i], states[j]),
            float(bool(cities[i] & cities[j])),
            float(bool(zips[i] & zips[j])),
            _min_km(points[i], points[j]),
            float(len(sdays[i] & sdays[j])),
            overlap,
            gap,
            math.log1p(min(n_not[i], n_not[j])),
            math.log1p(max(n_not[i], n_not[j])),
            (min(li, lj) / max(li, lj)) if max(li, lj) > 0 else math.nan,
        ))
    return pd.DataFrame(rows, columns=FEATURES)

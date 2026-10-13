"""Candidate pairs: the few company pairs worth scoring out of ~n²/2.

Three key families, unioned:
- **Char-trigram neighbours.** TF-IDF on the canonical name, cosine k-NN.
  Catches spelling and punctuation variants ("Kmart Corp" / "K-Mart Corporation").
- **First significant token + state.** Catches site-suffixed variants whose
  tails swamp the trigram vector ("ABM Industries - Bldg 1120 Main St").
- **Rare tokens.** Any token shared by at most RARE_DF profiles. Catches
  reordered or partial names that share one distinctive word.

Blocks larger than MAX_BLOCK are skipped; the trigram family still covers
their members. Pairs are (a, b) row positions with a < b.
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

from warn_v2.companies.normalize import _GENERIC_MATCH_TOKENS, _LEGAL_SUFFIXES, _STOPWORDS

K_NEIGHBOURS = 10
MIN_COSINE = 0.5
MAX_BLOCK = 100
RARE_DF = 20


_SKIP = _STOPWORDS | _LEGAL_SUFFIXES


def _tokens(name: str) -> list[str]:
    return [t for t in name.split() if t not in _SKIP and len(t) > 1 and not t.isdigit()]


def _pairs_from_blocks(blocks: dict[object, list[int]]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for members in blocks.values():
        uniq = sorted(set(members))
        if 2 <= len(uniq) <= MAX_BLOCK:
            out.update(combinations(uniq, 2))
    return out


def trigram_pairs(names: pd.Series, k: int = K_NEIGHBOURS,
                  min_cosine: float = MIN_COSINE) -> set[tuple[int, int]]:
    if len(names) < 2:
        return set()
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 3), min_df=1)
    X = vec.fit_transform(names.fillna("").to_numpy())
    nn = NearestNeighbors(n_neighbors=min(k + 1, len(names)), metric="cosine",
                          algorithm="brute").fit(X)
    dist, idx = nn.kneighbors(X)
    out: set[tuple[int, int]] = set()
    for i in range(len(names)):
        for d, j in zip(dist[i], idx[i], strict=True):
            if j != i and 1.0 - d >= min_cosine:
                out.add((min(i, int(j)), max(i, int(j))))
    return out


def token_state_pairs(profiles: pd.DataFrame) -> set[tuple[int, int]]:
    blocks: dict[object, list[int]] = defaultdict(list)
    for i, (name, states) in enumerate(zip(profiles["cleaned"], profiles["states"],
                                           strict=True)):
        toks = _tokens(name)
        if toks:
            for st in states or {""}:
                blocks[(toks[0], st)].append(i)
    return _pairs_from_blocks(blocks)


def rare_token_pairs(profiles: pd.DataFrame, rare_df: int = RARE_DF) -> set[tuple[int, int]]:
    blocks: dict[object, list[int]] = defaultdict(list)
    for i, name in enumerate(profiles["canonical"]):
        for t in set(_tokens(name)) - _GENERIC_MATCH_TOKENS:
            blocks[t].append(i)
    return _pairs_from_blocks({t: m for t, m in blocks.items() if len(m) <= rare_df})


def candidate_pairs(profiles: pd.DataFrame) -> pd.DataFrame:
    """Union of the three families: columns a, b (row positions, a < b)."""
    pairs = (trigram_pairs(profiles["canonical"])
             | token_state_pairs(profiles)
             | rare_token_pairs(profiles))
    arr = np.array(sorted(pairs), dtype=int).reshape(-1, 2)
    return pd.DataFrame({"a": arr[:, 0], "b": arr[:, 1]})


def pair_completeness(candidates: pd.DataFrame, positives: pd.DataFrame) -> float:
    """Share of known matching pairs (a, b with a < b) that blocking keeps."""
    if positives.empty:
        return float("nan")
    cand = set(zip(candidates["a"], candidates["b"], strict=True))
    hits = sum((a, b) in cand for a, b in zip(positives["a"], positives["b"], strict=True))
    return hits / len(positives)

"""Deterministic gate for /layoff-sentiment reports. Stdlib only.

Checks every published report against the payloads.json it was written from:

- structure: the H1 the SPA expects, a "_Generated <as_of>" line, and the
  required ## sections;
- markdown: only the subset frontend/src/components/ReportMarkdown.tsx renders
  (no links, inline code, ### headings, numbered lists, *single* italics, HTML),
  and every pipe table has a consistent column count;
- framing: no growth vocabulary (add/grow/gain in any form) outside tables;
- length: the Sentiment section is at most 250 words of plain prose;
- grounding: every number and date in the report appears in that report's
  payload (or is one of a few fixed constants such as the 90-day window).

Usage (from the repo root):
    python .claude/skills/layoff-sentiment/validate.py PAYLOADS_JSON [REPORT.md ...]
With no report paths it checks every *.md in warn_v2/reports/published/.
Exit 0 when every report passes; otherwise prints one line per problem, exit 1.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PUBLISHED = Path("warn_v2/reports/published")
MAX_SENTIMENT_WORDS = 250

BANNED_RE = re.compile(
    r"\b(add(?:s|ed|ing)?|grow(?:s|ing|n)?|grew|gain(?:s|ed|ing)?)\b", re.IGNORECASE
)
UNSUPPORTED = [
    (re.compile(r"\]\("), "markdown link"),
    (re.compile(r"`"), "inline code"),
    (re.compile(r"^#{3,}\s", re.MULTILINE), "### heading (only # and ## render)"),
    (re.compile(r"^\s*\d+[.)]\s", re.MULTILINE), "numbered list"),
    (re.compile(r"(?<![*\w])\*(?!\*)[^*\n]+?(?<!\*)\*(?![*\w])"), "*single* italics"),
    (re.compile(r"<[A-Za-z/!]"), "raw HTML"),
    (re.compile(r"^\s+[-*]\s", re.MULTILINE), "nested list"),
]
# Fixed figures a report may cite that aren't payload values: the window
# lengths (90 days, 12 months, 6-month outlook, 80% band), the score formula
# (0-100; 50/30/20 weights; grade cut-offs 80/60/40/20), "3-digit" subsectors,
# "top 10" rows, and the 250-word / 50% coverage thresholds.
CONSTANTS = {0, 3, 6, 10, 12, 20, 30, 40, 50, 60, 80, 90, 100, 365}

# Digit lookarounds, not \b: "_" (the italic marker) is a word character.
DATE_RE = re.compile(r"(?<!\d)\d{4}-\d{2}(?:-\d{2})?(?!\d)")
NUM_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def _walk(node, numbers: set[float], strings: set[str]) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, (int, float)):
        numbers.add(abs(float(node)))
    elif isinstance(node, str):
        strings.add(node)
        for d in DATE_RE.findall(node):
            strings.add(d)
        for n in NUM_RE.findall(DATE_RE.sub(" ", node)):
            numbers.add(float(n.replace(",", "")))
    elif isinstance(node, dict):
        for k, v in node.items():
            _walk(k, numbers, strings)
            _walk(v, numbers, strings)
    elif isinstance(node, list):
        for v in node:
            _walk(v, numbers, strings)


def _grounded(token: str, numbers: set[float]) -> bool:
    value = float(token.replace(",", ""))
    if value in CONSTANTS or value in numbers:
        return True
    # A payload 12.34 may be cited at the precision the report uses ("12.3%").
    decimals = len(token.split(".")[1]) if "." in token else 0
    return any(round(n, decimals) == value for n in numbers if not n.is_integer())


def _payload_for(name: str, doc: dict) -> tuple[str, dict | None]:
    stem = name.removesuffix(".md")
    if stem.startswith("industry_"):
        sector = stem.removeprefix("industry_")
        return "industry", doc["industries"].get(sector)
    return "jurisdiction", doc["jurisdictions"].get(stem)


def _sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = ""
        elif current is not None:
            out[current] += line + "\n"
    return out


def _check_tables(text: str) -> list[str]:
    problems = []
    block: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            cols = [len(re.split(r"(?<!\\)\|", row.strip().strip("|"))) for row in block]
            if len(set(cols)) != 1:
                problems.append(f"table starting {block[0][:40]!r} has ragged rows {cols}")
            elif len(block) < 2 or not re.fullmatch(r"\|[\s:|-]+\|", block[1].strip()):
                problems.append(f"table starting {block[0][:40]!r} lacks a --- header row")
            block = []
    return problems


def validate(path: Path, doc: dict) -> list[str]:
    text = path.read_text(encoding="utf-8")
    kind, payload = _payload_for(path.name, doc)
    if payload is None:
        return [f"no payload for {path.name}"]
    problems: list[str] = []

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if kind == "industry":
        h1 = f"# {payload['sector_name']} (NAICS {payload['sector']}) — Industry Scorecard"
        required = ["Scorecard", "Summary", "Sentiment", "Monthly trend"]
    else:
        h1 = f"# {payload['state_name']} ({payload['state']}) — WARN Layoff Trends"
        required = ["Summary", "Sentiment", "Monthly trend"]
    if not lines or lines[0] != h1:
        problems.append(f"first line must be {h1!r}")
    if len(lines) < 2 or not lines[1].startswith(f"_Generated {doc['as_of']}"):
        problems.append(f"second line must start '_Generated {doc['as_of']}'")

    sections = _sections(text)
    for name in required:
        if not any(s == name or s.startswith(name + " ") for s in sections):
            problems.append(f"missing '## {name}' section")
    sentiment = sections.get("Sentiment", "")
    words = len(sentiment.split())
    if words > MAX_SENTIMENT_WORDS:
        problems.append(f"Sentiment is {words} words (max {MAX_SENTIMENT_WORDS})")
    if re.search(r"^\s*(\||[-*>]\s)", sentiment, re.MULTILINE):
        problems.append("Sentiment must be plain prose (no tables, lists, or quotes)")

    for pattern, label in UNSUPPORTED:
        if m := pattern.search(text):
            problems.append(f"unsupported markdown ({label}): {m.group()[:40]!r}")
    problems += _check_tables(text)

    prose = "\n".join(ln for ln in text.splitlines() if not ln.startswith("|"))
    for m in BANNED_RE.finditer(prose):
        problems.append(f"banned growth word {m.group()!r} — job losses rose/eased, never grew")

    numbers: set[float] = set()
    strings: set[str] = {doc["as_of"]}
    _walk(payload, numbers, strings)
    body = text.split("\n", 1)[1] if "\n" in text else ""  # H1 checked above
    for d in DATE_RE.findall(body):
        if d not in strings:
            problems.append(f"date {d} is not in the payload")
    for token in NUM_RE.findall(DATE_RE.sub(" ", body)):
        if not _grounded(token, numbers):
            problems.append(f"number {token} is not in the payload")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    doc = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    paths = [Path(p) for p in argv[1:]] or sorted(PUBLISHED.glob("*.md"))
    failed = 0
    for path in paths:
        problems = validate(path, doc)
        if problems:
            failed += 1
            for p in problems:
                print(f"{path.name}: {p}")
    print(f"checked={len(paths)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

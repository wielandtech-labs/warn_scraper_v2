#!/usr/bin/env bash
# Fail when the chart changed but its version did not move past the base's.
#
# Flux packages charts/warn-v2 with reconcileStrategy: ChartVersion, so a
# template change that ships under an unchanged `version:` is never
# repackaged: Helm keeps rendering the old templates and everything still
# reports Ready (seen 2026-07-02, two PRs both targeting 0.1.21). See
# CLAUDE.md, "Helm chart version".
#
# Usage: check_chart_version.sh <base-ref> [<head-ref>]
#   base-ref  the commit the change sits on: HEAD^1 for a PR merge commit
#             (CI), or origin/main locally
#   head-ref  defaults to HEAD
set -euo pipefail

CHART_DIR="charts/warn-v2"
base="${1:?usage: check_chart_version.sh <base-ref> [<head-ref>]}"
head="${2:-HEAD}"

chart_version() {
  git show "$1:$CHART_DIR/Chart.yaml" | sed -n 's/^version:[[:space:]]*//p' | tr -d "\"'" | head -n 1
}

if git diff --quiet "$base" "$head" -- "$CHART_DIR"; then
  echo "No changes under $CHART_DIR; chart version check skipped."
  exit 0
fi

base_version="$(chart_version "$base")"
head_version="$(chart_version "$head")"
if [ -z "$base_version" ] || [ -z "$head_version" ]; then
  echo "::error::Could not read version: from $CHART_DIR/Chart.yaml (base='$base_version', head='$head_version')."
  exit 1
fi

newest="$(printf '%s\n%s\n' "$base_version" "$head_version" | sort -V | tail -n 1)"
if [ "$head_version" = "$base_version" ] || [ "$newest" != "$head_version" ]; then
  echo "::error file=$CHART_DIR/Chart.yaml::$CHART_DIR changed but version: is $head_version and the base branch has $base_version. Bump version: above $base_version, or Flux will not repackage the chart and the template changes will never deploy."
  exit 1
fi

echo "Chart changed and version moved $base_version -> $head_version."

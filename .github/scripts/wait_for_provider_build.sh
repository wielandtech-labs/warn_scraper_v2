#!/usr/bin/env bash
# Wait for the provider image rebuild that docker.yml just dispatched, and
# fail if it does not succeed.
#
# The dispatch API call returns nothing about the run it starts, and nothing
# else reports the result: on 2026-10-16 every provider build failed after
# #382 and the enricher enriched 0 for two days before anyone looked (see
# CLAUDE.md, "The enricher runs a DIFFERENT image"). This turns that into a
# red run on main.
#
# Environment:
#   DISPATCH_TOKEN   token that can read Actions runs on the provider repo
#   DISPATCH_REPO    "<owner>/<repo>" of the provider repo (a secret: this
#                    script never prints it, nor any URL that contains it)
#   SINCE            ISO-8601 UTC time just before the dispatch
#   WORKFLOW         workflow file in the provider repo   (default docker.yml)
#   FIND_TIMEOUT     seconds to wait for the run to appear       (default 300)
#   WAIT_TIMEOUT     seconds to wait for it to finish           (default 1500)
#   POLL_INTERVAL    seconds between polls                        (default 15)
#   GITHUB_API_URL   API base                    (default https://api.github.com)
#
# The run is identified as the oldest workflow_dispatch run of WORKFLOW on
# main created at or after SINCE. Two warn-v2 merges within the same minute
# could therefore watch each other's run; docker.yml's concurrency group makes
# that rare, and either way a failed provider build still turns a run red.
set -euo pipefail

: "${DISPATCH_TOKEN:?DISPATCH_TOKEN is required}"
: "${DISPATCH_REPO:?DISPATCH_REPO is required}"
: "${SINCE:?SINCE is required}"
WORKFLOW="${WORKFLOW:-docker.yml}"
FIND_TIMEOUT="${FIND_TIMEOUT:-300}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-1500}"
POLL_INTERVAL="${POLL_INTERVAL:-15}"
API="${GITHUB_API_URL:-https://api.github.com}"

api() {
  # -f: an HTTP error is a failed call. Errors go to /dev/null because curl's
  # message would include the URL, and with it the repo name.
  curl -sSf -G \
    -H "Authorization: Bearer $DISPATCH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "$@" 2>/dev/null
}

echo "Looking for the provider build dispatched at or after $SINCE."
run_id=""
deadline=$(( $(date +%s) + FIND_TIMEOUT ))
while [ -z "$run_id" ]; do
  if runs="$(api "$API/repos/$DISPATCH_REPO/actions/workflows/$WORKFLOW/runs" \
      --data-urlencode "event=workflow_dispatch" \
      --data-urlencode "branch=main" \
      --data-urlencode "created=>=$SINCE" \
      --data-urlencode "per_page=20")"; then
    run_id="$(jq -r '[.workflow_runs[]] | sort_by(.created_at) | (.[0].id // empty)' <<<"$runs")"
  else
    echo "::warning::Could not list provider workflow runs (token scope, or the API is unavailable); retrying."
  fi
  if [ -z "$run_id" ]; then
    if [ "$(date +%s)" -ge "$deadline" ]; then
      echo "::error::The provider rebuild was dispatched but no run appeared within ${FIND_TIMEOUT}s. The enricher image has NOT been rebuilt on this base. Check the provider repo's docker.yml runs."
      exit 1
    fi
    sleep "$POLL_INTERVAL"
  fi
done
echo "Found provider build run $run_id; waiting for it to finish."

deadline=$(( $(date +%s) + WAIT_TIMEOUT ))
while :; do
  status=""; conclusion=""
  if run="$(api "$API/repos/$DISPATCH_REPO/actions/runs/$run_id")"; then
    status="$(jq -r '.status // ""' <<<"$run")"
    conclusion="$(jq -r '.conclusion // ""' <<<"$run")"
  fi
  if [ "$status" = "completed" ]; then
    if [ "$conclusion" = "success" ]; then
      echo "Provider build run $run_id succeeded."
      exit 0
    fi
    echo "::error::Provider build run $run_id finished with conclusion '$conclusion'. Prod keeps the previous provider image while chart changes still apply to it. Fix the provider build before relying on this release for enrichment."
    exit 1
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "::error::Provider build run $run_id did not finish within ${WAIT_TIMEOUT}s (last status: '${status:-unknown}'). Check the provider repo's docker.yml runs."
    exit 1
  fi
  sleep "$POLL_INTERVAL"
done

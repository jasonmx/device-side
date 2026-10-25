#!/usr/bin/env bash
# Exit 0 only when at least one workflow run is attached to <sha> and every one concluded success: the rule a
# release gate needs before tagging. The cut-* release workflows are left out, so a gate never waits on itself or
# on an earlier refused cut. Of several runs of one workflow and event (a nightly rerun), the latest counts.
# Needs GH_TOKEN and GITHUB_REPOSITORY, as a workflow step has them.
#
# Usage: scripts/require_green.sh <sha>
set -euo pipefail

sha=${1:?usage: scripts/require_green.sh <sha>}
runs=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs?head_sha=$sha&per_page=100" --jq '
  [.workflow_runs[] | select(.path | startswith(".github/workflows/cut-") | not)]
  | group_by([.path, .event]) | map(max_by(.created_at))[]
  | "\(.conclusion // .status)\t\(.name) (\(.event))"')

if [ -z "$runs" ]; then
  echo "::error::No workflow run on $sha; push it and let CI finish first."
  exit 1
fi
echo "$runs"
if not_green=$(printf '%s\n' "$runs" | grep -v '^success'); then
  echo "::error::Not every run on $sha concluded success:"
  echo "$not_green"
  exit 1
fi

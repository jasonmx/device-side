#!/bin/sh
# Install the integration at <branch>'s tip on origin into the rig HA, then restart HA.
# Run by scripts/rig.py behind its approval gate, not by hand: the restart drops every automation in the house.
# RIG_SYNC_CMD and RIG_RESTART_CMD are set in .env.rig and passed here by the runner.
set -eu

branch=${1:?usage: deploy.sh <branch> [--no-restart]}
: "${RIG_SYNC_CMD:?RIG_SYNC_CMD is not set; add it to .env.rig (see tests/rig/env.example)}"

$RIG_SYNC_CMD "$branch"
if [ "${2:-}" != "--no-restart" ]; then
  : "${RIG_RESTART_CMD:?RIG_RESTART_CMD is not set; add it to .env.rig (see tests/rig/env.example)}"
  $RIG_RESTART_CMD
fi

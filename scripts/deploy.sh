#!/bin/sh
# Install the integration at <branch>'s tip on origin into the rig HA, then restart HA.
# Run by scripts/rig.py behind its approval gate, not by hand: the restart drops every automation in the house.
# Both steps are verbs of pi-stack's ha-shim, which pins the RIG_SSH key; there is no rsync to the Pi.
set -eu

branch=${1:?usage: deploy.sh <branch> [--no-restart]}
host=${RIG_SSH:-ha}

ssh "$host" ds-sync "$branch"
if [ "${2:-}" != "--no-restart" ]; then
  ssh "$host" restart homeassistant
fi

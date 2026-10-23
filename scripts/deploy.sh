#!/bin/sh
# Install the integration at <branch>'s tip on origin into the rig HA, then restart HA.
# Run by scripts/rig.py behind its approval gate, not by hand: the restart drops every automation in the house.
# Both steps are verbs of the maintainer's deploy tooling, which pins the RIG_SSH key; there is no rsync to the Pi.
set -eu

branch=${1:?usage: deploy.sh <branch> [--no-restart]}
host=${RIG_SSH:-ha}

ssh "$host" the deploy sync verb "$branch"
if [ "${2:-}" != "--no-restart" ]; then
  ssh "$host" restart homeassistant
fi

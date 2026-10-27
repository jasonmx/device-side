# device_side

Design and delivery plan: `docs/plans/2026-10-23-device-side-repo-plan.md`. Use its glossary's terms in code
and docs; "platform", "backing" and "claim" are retired.

When an action should raise, skip a target, or what its response holds: match core, per `docs/action-behavior.md`.

**The repo is public:** no household entity IDs, device names, MACs or hostnames anywhere in it, commit messages included.

**No personal tooling:** deploy hosts, SSH aliases, and private stacks belong in gitignored files (`.env.rig`, `notes/`, `CLAUDE.local.md`), not in committed code, docs or commit messages.

## Tiers

A tier belongs to an **adapter** (action × integration) and covers its whole scope
(`AdapterScope.domains`, `.capabilities`, `.fields` and `.options`).

| Tier | Meaning | Bar |
|---|---|---|
| experimental | design in flux | `experimental=True` on the adapter; no coverage bar |
| untested | design settled | ≥95% line coverage of the adapter module; some of its scope not yet covered by a bench record |
| beta | tested on hardware | at least one bench record (rig run or tester report) with the current fingerprint, and every capability, field and option in scope covered (below) |
| stable | released | on `main`; everything on `main` is stable |

Only `experimental` is declared; `scripts/check_tiers.py` computes the rest from every
`docs/bench/<integration>/<action>*.md` record of the adapter. CI prints the tiers; only `cut-release`
requires every adapter beta. Fingerprint = AST hash of the adapter module and, in turn, the modules it imports
from its own integration package (`from .x import`), excluding docstrings and the `AdapterScope` declaration; any
other change resets the adapter to `untested` until a record carries the new fingerprint. Regressions block promotion; they never demote.

**Capabilities carry forward, fields don't.** A capability listed by any passing record (any
fingerprint) stays covered while the adapter has a current-fingerprint record that reached the device; a field needs a
current-fingerprint record listing it. An option needs current-fingerprint records with it on and with it
off (a record's `Options` row; absent means all off).

**Proof follows the call.** A bench record proves the call an adapter sends and the capability it
reaches (Shelly: the RPC component), whatever entity domain the target shows: a relay exposed as a
`switch` or an on/off `light` rides one record. Records list the capabilities and fields they
exercised. A capability or field nobody has tested is left out of scope and refused, never added on
a sibling's proof. Adding one after a tester report is a scope edit plus a record listing it.

**Setting `experimental`:** set it for a new action, a new field or attribute, or a new integration
(including ports). Leave it off for fixes, refactors and performance work. When unsure, ask.

## Pull requests

- Base: whichever is newer, `main` or the latest `release/vX.Y.Z` branch.
- Setup: `uv sync`. Test dependencies live in the `dev` group of `pyproject.toml`; never `uv pip install` into `.venv`, as the next sync removes it.
- Before each push: `.venv/bin/pytest` and `pre-commit run --all-files` (ruff and the household check).
- Before opening the PR: `/audit-code` on the diff, then fix what you judge worth fixing and carry on to the PR;
  stop for Jason only on a big judgment call.

## Layout

- `custom_components/device_side/core/`: registry, resolver, dispatcher, action registration
- `custom_components/device_side/actions/`: one module per action
- `custom_components/device_side/integrations/<integration>/`: one adapter module per action
- `tests/{core,actions,integrations,rig}`: mirror the above; `rig/` drives the live HA, only via `scripts/rig.py`
- `scripts/`: rig runner, household check, deploy, release checks (tiers, tags, RC audits)
- `docs/bench/<integration>/`: bench records. Design detail lives in the repo plan.

## Conventions

- Async throughout; `_LOGGER = logging.getLogger(__name__)`; actions registered once in `async_setup`.
- American English, matching HA. The version lives in `manifest.json`.

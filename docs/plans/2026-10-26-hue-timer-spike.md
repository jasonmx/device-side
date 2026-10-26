# Hue timed on/off: bench spike (open item 10)

## Context

7a has landed. The Hue port plan (`docs/plans/2026-10-25-hue-port.md`) puts Hue `turn_on_for`/`turn_off_for` (7d)
after 7b/7c, gated on open item 10 of the repo plan. That gate is a bridge question, not a code dependency, and
its answer may change the cancel contract on **every** integration (`cancel_delayed_toggle`), so we want it
before the first RC. Decision (2026-10-25): **spike now alongside 7b, build later.** No adapter code in this
session. The fallback, if the bridge can't honor the cancel contract, is decided **after** the results are in.

Known going in: aiohue's `BehaviorInstanceController` (`aiohue/v2/controllers/config.py`) can update, enable,
`start` and `stop` an instance, but has no create, so creating one is a raw `POST clip/v2/resource/behavior_instance`.
The handoff (`docs/device_side_handoff-2026-10-23.md` §5, §7.1) lists the caveats to test.

## Steps

1. **Worktree** `wt/hue-timer-spike` off `release/v0.0.2` (only the plan edit gets committed).
2. **Discover** (read-only): a scratchpad script (`uv run`, PEP 723, aiohttp) that lists `behavior_script`
   resources on the rig bridge and dumps the configuration schema of the timer-like scripts (the Hue app's
   "Timers" one). Bridge host and app key come from Jason through a gitignored main-checkout file (e.g.
   `.env.rig` entries he adds), never committed or printed. Output: can a one-shot "off after N s" on one light,
   or on a `grouped_light`, be expressed? What's the minimum N, and how fine is the resolution?
3. **Experiments** on a `light_ct` rig bulb. The script does the steps and logs the bulb's on/off and the
   instance's `status`/`state` every second; Jason does the physical ones when the script asks:
   - a. Timer start semantics (on create, on enable, or needs `start`) and expiry accuracy against the 2 s
     Hue `TOLERANCE_S`.
   - b. Cancel by plain `light.turn_on` / `light.turn_off` through HA.
   - c. Cancel by a Hue app toggle (Jason). Cancel by a dimmer switch press (Jason).
   - d. Cancel by deleting the instance, and by disabling it.
   - e. A second timer while one runs: does it stack or replace? Is a deterministic `metadata.name` enough to
     find and replace it?
   - f. Cleanup: does a one-shot instance remain after it fires, and does it show in the Hue app? Is there an
     instance count limit?
   - g. Bulb unreachable at expiry (Jason cuts its power): stays on as predicted?
   - h. `turn_off_for` shape: off now, then on after N s, with the same cancel checks b and d.
   The script deletes every instance it created in a `finally` and restores the bulb.
4. **Record**: answer open item 10 in `docs/plans/2026-10-23-device-side-repo-plan.md` (each question with
   its result, firmware and date) and point 7d in the Hue port plan at it. Public repo: no IDs, names or
   hosts. Raw logs stay in the scratchpad or `notes/`.
5. **Decide with Jason**: native cancel works / `cancel_delayed_toggle` everywhere / Hue `unsupported`. The
   decision goes into the repo plan's Scope cancel-contract bullet. 7d then gets its own short plan in a fresh
   session.
6. PR into `release/v0.0.2` (docs only), `ci-green`, squash-merge, remove the worktree.

## Verification

- Every question in open item 10 and handoff §7.1 has a recorded answer, or is explicitly marked open with the reason.
- `git diff` holds no household identifiers; `pre-commit run --all-files` (household check) passes.
- No `behavior_instance` created by the spike is left on the bridge (list it again at the end).

# Slice 13d: Matter `get_attributes`

## Context

Slice 13 (`docs/plans/2026-10-27-zigbee-parity-timer-state.md`) adds on/off timer state to `get_attributes`.
13b added the contract (the `switch` domain and `core/timer.py:timer_row`). 13c (#105) was the first adapter,
for Shelly. 13d does the same for the Matter plug, which runs `OnWithTimedOff` through `MatterTurnOnFor`. A
`get_attributes` on it returns `timer: {turns: "off", ends_at, remaining_s}` while the countdown runs, and an
empty entry when no timer is running.

Decided in the interview (2026-10-28):
- **Probe the cache first.** The slice plan reads OnTime from the node cache. The device reports only on its
  subscription interval, though, so a probe compares the cache with a live read before the adapter is written,
  and a fixed rule (step 1) picks the source.
- **No `experimental` flag.** As with Shelly, the bench record lands in this PR. The rig plug covers the whole
  scope: `switch` only, the same as `turn_on_for` (#91).

## Steps

0. **Set up.** Create worktree `wt/matter-get-attributes` off `release/v0.0.2`. The first commit saves this plan as
   `docs/plans/2026-10-28-matter-get-attributes.md`.

1. **Probe: is the cache fresh enough?** Read-only, apart from the timer it starts. The rig is pre-authorized for
   2026-10-28. Check the rig lock first (memory: rig shared with other sessions). Use a scratch script in the
   scratchpad that connects to the Matter server's WebSocket (`:5580` on the HA host). Take the address from
   `.env.rig` in the main checkout, and keep it out of the repo. If the port can't be reached, use HA's device
   diagnostics download (admin token) for the cache side; the live side is already proven by
   `turn_on_for`. Send a 20 s `OnWithTimedOff` to the plug, then sample once a second until it ends:
   - the cached `"{ep}/6/16385"` from `get_node`/node events;
   - a live `read_attribute` of the same path;
   - whether a plain `On` sent partway through, and then an `Off`, clear `OnTime`. This feeds the doc's
     "Cancelling" text.

   **Rule:** if the cached value stays within 1 s of the live read at every sample, and is 0 within 2 s of the
   timer ending, read from the cache (sync, no I/O). Otherwise read live. Write the sample table into the plan
   doc's Findings section, and tell Jason the outcome in a line. This gates nothing unless a finding contradicts a
   step below.

2. **Shared refusal: `matter/addressing.py`.** Move the body of `MatterTurnOnFor.supports` after `super()`
   (unique-ID parse, client, node lookup, `lt_feature`) into `unsupported_reason(hass, target) -> str | None`.
   Name it to match `shelly/addressing.py:unsupported_reason`, and have `turn_on_for` call it.
   Without LT there is no `OnTime`, so `get_attributes` refuses `no_lt_feature` too.

3. **Adapter: `integrations/matter/get_attributes.py`** `MatterGetAttributes(Adapter[Request])`:
   - Scope: `AdapterScope(domains={"switch"}, fields=frozenset(), confirmable=True)`, with turn_on_for's comment
     about lights waiting for a tester.
   - `supports`: `super().supports(...) or unsupported_reason(hass, target)`.
   - `execute`: one `OnTime` per target through `self.gather`, from the source step 1 picked. For a live read,
     use `client.read_attribute(node_id=…, attribute_path=ontime_attr_path(ep))` and take `.get(path)`. Errors
     propagate (9f: a device error raises, and `gather` rejects that target). If the cache is used and the path
     is missing, the cache can't answer, so fall back to a live read for that target.
   - Pure row function `on_time_row(on_time, now)`: when `on_time` is a positive int, return
     `{"timer": timer_row("off", on_time / 10, now)}`. Otherwise return `{}`. `OnTime` > 0 alone means a timer
     is running, because the spec only counts it down while the plug is on and `Off` zeroes it. Matter has no
     `turn_off_for`, so `turns` is always `"off"`.
   - Register it in `integrations/matter/__init__.py` `ADAPTERS`. Add `- domain: switch, integration: matter`
     under `get_attributes` in `services.yaml`.

4. **Unit tests: `tests/integrations/matter/test_get_attributes.py`.** Use the existing `tests/fixtures/matter.py`
   (`matter_device`, `on_time_reads`, and a cache attribute if step 1 picks the cache). Freeze `now` and assert
   whole rows. Cover:
   - a running timer (tenths converted to seconds, with `ends_at`);
   - zero, and a path missing from the answer, which give `{}`;
   - refusals: `no_lt_feature`, the `light` domain, an unparsable unique_id, and an unreachable node;
   - a read error, which rejects that target;
   - two targets in one call, one with a timer and one without.

   `turn_on_for`'s tests must still pass after the step 2 move. Both modules need ≥95% coverage.

5. **Docs.**
   - `docs/integrations.md`: 13c pasted Shelly's `get_attributes` section into the Zigbee2MQTT and Matter
     sections as well. Delete the Z2M copy. Replace the Matter copy with Matter's real behavior: one `OnTime` per
     target, from the source step 1 picked; the timer row; an empty entry when no timer runs; a read that fails
     raises. If step 1 shows a plain `On` doesn't clear `OnTime`, fix the Matter "Cancelling" text too.
   - `README.md` "Read Timer and Color" row, Matter column: `✅ switches<br>🙋 lights`, the same as its
     `turn_on_for` cell.

6. **Rig steps: `tests/rig/steps/get_attributes.yaml`.**
   - `reads_a_turn_off_for_timer`: add `only: [shelly]`, with the comment "Matter has no OffWithTimedOn". Without
     it, the step would call a `turn_off_for` that Matter refuses.
   - `reads_a_running_timer`: after the first read, add `wait: 5`, then expect `timer.remaining_s` `{min: 10,
     max: 16}`. This proves the device counts down rather than echoing the duration. It applies to every
     integration, so Shelly is rerun too.

7. **Rig run.** Check the lock and the deployed tree, then run `scripts/rig.py --action get_attributes` in the
   background. Write `docs/bench/matter/get_attributes.md` (WiZ plug, `switch`) from the run. Refresh
   `docs/bench/shelly/get_attributes.md` from the same run, because its step file changed.

8. **Land it.**
   - Run `.venv/bin/pytest`, `pre-commit run --all-files`, `scripts/check_release.py --coverage`, then `/audit-code`
     on the diff, and fix what it finds.
   - In the same PR, mark 13d done in the slice 13 plan and tick it in `TODO.md`.
   - Open a PR into `release/v0.0.2`, run `merge-green <n> --squash --delete-branch` in the background, then
     remove the worktree.

## Critical files

- New: `integrations/matter/get_attributes.py`, `tests/integrations/matter/test_get_attributes.py`,
  `docs/bench/matter/get_attributes.md`, `docs/plans/2026-10-28-matter-get-attributes.md`
- Edited: `integrations/matter/{__init__,addressing,turn_on_for}.py`, `services.yaml`, `tests/fixtures/matter.py`
  (only if the cache is picked), `tests/rig/steps/get_attributes.yaml`, `docs/integrations.md`, `README.md`,
  `docs/bench/shelly/get_attributes.md`, the slice 13 plan, `TODO.md`
- Reused: `core/timer.py:timer_row`, `matter/addressing.py` (`ontime_attr_path`, `matter_client`, `lt_feature`),
  `shelly/get_attributes.py` as the pattern for the adapter shape

## Verification

- Unit: run `.venv/bin/pytest tests/integrations/matter tests/actions`, then `scripts/check_release.py --release`
  (it must not flag the Matter adapter).
- Probe: the sample table in the plan doc, which shows the source rule's outcome.
- Rig: a passing `get_attributes` run in which the Matter plug reads a live timer that counts down and then
  clears, and the Shelly cases still pass with the new countdown check.

# Hue ramp end-value report: bench spike

## Context

When a Hue ramp starts, the bridge sends one event holding the ramp's **end value**. After a stop mid-ramp it
takes about 10 s to send the value where the light halted. HA's Hue integration copies these events as they
arrive (`homeassistant/components/hue/v2/light.py:127` reads the aiohue model and adds nothing of its own), so HA
shows the end value too. 7b's `TransitionCache` (`hue-move` worktree, `integrations/hue/transition_cache.py`)
handles this with a timer: it predicts brightness instead of reading the bridge for `API_SETTLE_SECONDS` (15 s)
plus the ramp's duration. A change made elsewhere during that window is missed, so the next `move` starts from
the wrong brightness.

The proposed design (agreed in conversation, 2026-10-26) has two layers:

- **Always on:** the cache drops only our own end value and treats any other brightness event from the bridge
  as real (`observe()`). A time limit applies only to how long it waits for the end value.
- **Behind an option, off by default:** a synchronous subscriber on `bridge.events` removes `dimming` from our
  end-value event before aiohue's controller applies it, so HA never shows it. device_side then sends its own
  local events (`bridge.events.emit`) with the end value when a ramp completes, and with the predicted value on
  a stop. These never reach the bridge.

Both layers depend on bridge behavior nobody has measured. This spike measures it. **No adapter code.** The
design is decided after the results are in.

## Questions

| # | Question | Decides |
|---|---|---|
| Q1 | Ramp start: how many brightness events per resource? Is the value exactly the target (rounding)? Does it arrive before or after the PUT response? Does `on` come in the same event? | how the filter matches the end value; setting the filter up before sending |
| Q2 | Ramp runs to completion: does any event arrive at the end? | whether the option layer needs a fake event at completion |
| Q3 | Stop mid-ramp: any event straight away? When does the correction arrive, how many events, and how far is it from linear interpolation? | prediction accuracy; how long a prediction lasts |
| Q4 | **Dim, stop, dim with a 1 s, 4 s and 8 s gap:** does the first stop's correction arrive during the second ramp? | **whether `observe()` works at all** (the main gating question) |
| Q5 | Second ramp to the same target before the correction: is an end-value event sent? | the time limit on the filter |
| Q6 | Zone (`grouped_light`) ramp: events for the zone and for each light, their values (an average?), order | handling one filter per resource |
| Q7 | Change from elsewhere inside the window (Hue app slider by Jason; HA `light.turn_on` from the script): does a real-valued event arrive promptly? | the bug fix itself |
| Q8 | Dim to off (`on: false` with a duration): when does `on: false` arrive, at the start or the end? What brightness comes with it? | whether the option also hides `on` |
| Q9 | A color temperature change on its own: does its event carry `dimming`? | `observe()` must look at the raw event, not HA state |
| Q10 | Informative: a color temperature ramp and stop behave the same way (for 7c) | 7c reuse |
| Q11 | Q4 for color temperature (`color_temperature_delta` stop); a color temperature ramp and stop on the zone | whether 7c can use `observe()`; part of 7c's zone question |

## Steps

1. **Worktree** `wt/hue-echo-spike` off `release/v0.0.2`. Commit this plan as
   `docs/plans/2026-10-26-hue-echo-spike.md`.
2. **Script** in the scratchpad, run with the main checkout's `.venv/bin/python` (aiohue is already in the
   `dev` group, pinned to HA's version):
   - Connects with `aiohue.HueBridgeV2`. Bridge host and app key are already in the main checkout's
     `.env.rig` (check the variable names there); they're read at run time and never printed.
   - Records with a **synchronous `bridge.events.subscribe` callback**, the same hook the option layer would use.
     For each event it logs time relative to the step start, resource type, a label (`L1`, `Z`, `Z.m1`…; never
     IDs or names), and the raw `on`, `dimming` and `color_temperature` fields. In the same callback it checks the
     dict is the same object the controller later applies (compare the aiohue model after the
     `create_task` runs). That confirms the dispatch ordering the option layer relies on.
   - In parallel, reuses `tests/rig/client.py` `HAClient` to log HA's `brightness`/`state` for the same entities,
     so we can confirm HA mirrors the bridge.
   - Sends the same writes as 7b's `move.py`: `controller.set_state(rid, on=…, brightness=limit,
     transition_time=ms)` and `set_dimming_delta(rid)` for stop. The PUT is timestamped before sending and
     after the response, for Q1.
   - Entities come from `tests/rig/inventory.yaml` `hue` roles `light_ct` and `group`, mapped to resource ids
     through the aiohue model.
   - Turns off `RIG_PAUSE` items with `scripts/rig.py` `pause`/`resume`. Records the starting state and puts
     it back in a `finally` (pattern of `tests/rig/engine.py` `Snapshot.take`/`restore`). Doesn't run during a
     rig run.
3. **Experiments** on `light_ct` with a 10 s sweep, unless stated otherwise. Each starts from a settled light
   (no events for 15 s):
   - a. 20% → 80% ramp, left to finish; log 30 s after (Q1, Q2).
   - b. Same ramp, stop at 3 s; log 30 s (Q3).
   - c. Ramp up, stop at 3 s, ramp down after a 1 s, 4 s and 8 s gap, stop 3 s later; log 30 s after each
     (Q4). Two runs of each gap.
   - d. Ramp to 100, stop at 3 s, ramp to 100 again after 2 s (Q5).
   - e. a and b on `group` (Q6).
   - f. b, then Jason moves the Hue app slider 4 s after the stop; repeat with an HA `light.turn_on` brightness
     call from the script (Q7).
   - g. 60% → off ramp, left to finish; then again with a stop at 3 s (Q8).
   - h. Light on and settled: color temperature only, no duration (Q9).
   - i. a and b for color temperature (Q10).
   - j. c for color temperature, ramping warmer then cooler, two runs per gap; i on `group` (Q11). Saturation is
     left to 7c: its stop writes the predicted xy, so no late correction arises, and no color bulb is paired yet.
4. **Record** the results under Hue "Tested behavior" in `docs/integrations.md` (one line per question, firmware,
   HA and aiohue versions, date) and add a short "Result" section to this plan. Public repo: no IDs, names,
   hosts. Raw logs stay in the scratchpad.
5. **Decide with Jason**, written into the Hue port plan's 7b section:
   - Q4 clean: build `observe()` into 7b's `TransitionCache` now.
   - Q4 shows corrections arriving during a later ramp: a different design (e.g. ignore events that match an
     earlier stop's predicted value), argued in a fresh session.
   - Then, separately, whether the option layer goes ahead, and whether it covers `on` (Q8). That becomes its own
     plan.
6. `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff. PR into `release/v0.0.2`, run
   `ci-green` in the background, squash-merge, remove the worktree and branch.

## Verification

- Each of Q1–Q11 has a recorded answer, or is marked open with the reason; Q4 has two runs per gap.
- The rig lights end in their starting state (check HA once at the end); paused items are back on.
- `git diff` holds no household identifiers; `pre-commit run --all-files` (household check) passes.

## Result

Run 2026-10-26 on the rig's Office Corner bulb and DS Test zone; versions and the public summary are in
`docs/integrations.md` (Hue, Tested behavior). Raw logs stayed in the session scratchpad.

| # | Answer |
|---|---|
| Q1 | One `dimming` event per light, ~70 ms after the PUT returns (after, never before), holding the stored target (80 → 79.84). `on` comes as a separate event only when it changes. |
| Q2 | Nothing at completion. |
| Q3 | No event from the stop itself. A report came 0.1–27 s later, one event, within 0.3 % of linear interpolation; after 4 of 16 stops none came within 30 s. |
| Q4 | **Not clean.** With a 1 s gap (1 of 2 runs) a report (35.18) arrived 2 s into the second ramp and was the last event. In 5 of 6 runs the first stop never got its own report. |
| Q5 | No event: the bridge already holds that value. No report of the stop either. |
| Q6 | Each light's end value at once, then the `grouped_light` average ~1 s later. After a stop the lights reported 0.1 s and 16 s apart. |
| Q7 | Prompt: HA `light.turn_on` within 0.25 s; Hue app slider about one event a second while dragging. |
| Q8 | `on: false` + brightness 0 at the start. 1 of 2 runs then got a mid-ramp report `on: true` at 17 % and nothing after it. A dimming stop is refused ("soft off"). |
| Q9 | A color temperature write's event holds only `color_temperature`. |
| Q10, Q11 | Color temperature matches brightness: end value at the start, late or missing stop reports (3 of 6 Q4-style runs got none), exact interpolation, and zone transitions work. |

The option layer's hook works: a synchronous `bridge.events` subscriber runs before the controller applies the
event, and removing `dimming` from the dict kept it out of aiohue's model.

Late reports look like the bulb's own, not a bridge timer: their timing varies widely, they can be skipped, and they can
arrive mid-ramp. "Any non-end-value event is real" therefore fails, so per step 5 `observe()` is not built into 7b
as designed.

Decided with Jason: recorded in the Hue port plan's 7b section.

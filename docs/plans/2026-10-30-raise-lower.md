# Raise and lower: brightness moves as their own actions

Branch `wt/raise-lower`, worktree `.worktrees/raise-lower`, off `release/v0.0.2`. Agreed with Jason 2026-10-30.

## Decisions

- **Brightness moves get their own actions, `raise` and `lower`**, with hue_dimmer's fields: `sweep_time` and
  `limit`. HA puts a direction in the action name (`cover.open_cover`/`close_cover`/`stop_cover`, `turn_on`/`turn_off`),
  so a brightness move needs one field fewer, its limit can be labeled for its direction, and hue_dimmer users
  migrate by changing only the domain, as they already do for the other actions.
  - `raise`: `sweep_time` (s, default 5, min 0.1), `limit` "Maximum brightness" (%, 1–100, step 0.2). Raise turns
    the light on.
  - `lower`: `sweep_time` as above, `limit` "Minimum brightness" (%, 0–99, step 0.2). Description: "The light
    turns off at 0 %. Choose 0.4 % or more to keep it on." Lower to 0 % is the existing plain soft off.
  - Behavior, responses and details (`at_limit`, `off`, `fields_dropped`, `clamped_to`) are today's brightness
    `move`'s, unchanged.
- **`move` keeps the color moves, one direction per call**: exactly one of `hue` and `saturation`. Two directions
  raise `ServiceValidationError` (new key `one_direction`); `brightness` and `brightness_limit` leave the schema, so
  passing them fails validation. Who moves two attributes at once is rare, and every combination would need its
  own proof. `saturation_limit` stays.
- **`stop` is unchanged:** it halts everything in flight on the target, including two moves started by separate
  calls. We don't promise how two overlapping moves behave together.
- **Color temperature stays dropped** (`2026-10-28-drop-color-temp-move.md`).
- Module names: `actions/raise_.py` (key `raise`; the underscore is PEP 8's for a keyword) and `actions/lower.py`;
  the same in each integration.

## Steps

1. **Actions.** `actions/raise_.py` and `actions/lower.py` share one request (`sweep_time`, `limit`) and one parse,
   in a small shared module or in `move.py`; the direction comes from the action. Trim `move.py` to hue and
   saturation and add the one-direction check. Update `services.yaml` (the `move` target loses
   `integration: hue`, since Hue has no color move until 7c2), `strings.json`, `translations/en.json` and
   `icons.json` (raise `mdi:brightness-up`-style icons, matching the existing ones).
2. **Hue.** The brightness fade in `hue/move.py` becomes `hue/raise_.py` and `hue/lower.py`, sharing the fade
   code (move what both need into a shared module, e.g. `hue/fade.py`). The Hue `move` adapter goes. `stop`,
   `report_filter` and `predicted_state` are unchanged; the raise and lower scopes carry `predicted_state`.
   7c2 (Hue saturation) later adds a Hue `move` adapter back.
3. **Zigbee2MQTT.** `brightness_fade` and its publish move to `zigbee2mqtt/raise_.py` and `lower.py`; `move.py`
   keeps saturation and hue. Keep the shared start/read-back code in one place. `stop` is unchanged.
4. **Unit tests.** `tests/actions/test_raise.py`, `test_lower.py`; `test_move.py` gains the one-direction refusal
   and loses brightness. Split `tests/integrations/{hue,zigbee2mqtt}/test_move.py` into raise, lower and (Z2M)
   move. Coverage ≥95 % per adapter module.
5. **Rig.**
   - `move.yaml`'s brightness cases go to `raise.yaml` and `lower.yaml` by the first call's direction; a case that
     calls both (`raise_after_soft_off`, `ha_change_mid_move`) uses a step-level `action:` for the other.
     `move-predicted_state.yaml` splits the same way. `move.yaml` keeps `saturation_to_a_limit`.
   - Already on this branch: `sample` reads dotted attributes (`hs_color.1`), with a test and `testing.md`. Keep it.
   - Already on this branch, to rework: drop the three combined `move.yaml` cases
     (`brightness_and_saturation_together`, `saturation_joins_a_brightness_move`,
     `brightness_joins_a_saturation_move`). Rewrite the two `stop.yaml` cases as two calls: `raise` (or `lower`),
     then 1 s later a `move` of saturation (or hue), then `stop` at 3 s, keeping each attribute's halt checks.
     Recompute the expected values in their comments, ranges and `observe` text for the 1 s offset. Their
     observed runs wait for the pre-release sweep.
   - Every `action: move` with brightness in `stop*.yaml` becomes `action: raise` or `action: lower`.
   - Fix `rig_seconds` in each file. `scripts/rig.py --action raise --action lower --action move --action stop
     --dry-run` must parse.
6. **Docs.**
   - `docs/integrations.md`: Hue and Z2M sections name raise/lower for brightness, move for color.
   - `docs/action-behavior.md`, `docs/contributing/testing.md` examples: brightness `move` calls become raise/lower.
   - Repo plan: the `move` bullet and "move/stop replace raise/lower by design and are the exception" (drop-in
     rule, near line 70) record this decision with a pointer here. `2026-10-25-hue-port.md`: a superseded note on
     the brightness `up | down` decision.
   - Bench records `docs/bench/{hue,zigbee2mqtt}/move*.md`: a note that their brightness rows prove the call
     `raise`/`lower` now send; new records come from the rig run below.
   - README: check every `move` mention and the hue_dimmer migration wording.
   - `TODO.md`: a slice row for this. It must land before 13j's Z2M freeze and the Z2M A60 run. 13f (ZHA
     `move`/`stop`, `wt/zha-move-stop`, paused) must split its move adapter the same way when it resumes: say so
     on its TODO line. That branch also edits `_CaseRun.reading` (group means); its merge keeps both changes.
7. **Checks and PR.** `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff, fix findings,
   PR into `release/v0.0.2`. Adapters stay `experimental`.
8. **Rig run, with Jason's go** (not pre-authorized): unattended, `--action raise --action lower --action move
   --action stop` on Hue and Z2M, after pushing (deploy needs the branch on origin). Commit the records
   (`raise.md`, `lower.md`, `move.md`, `stop.md`, with `-predicted_state` variants) in the PR. Then
   `merge-green <n> --squash --delete-branch`, backgrounded.

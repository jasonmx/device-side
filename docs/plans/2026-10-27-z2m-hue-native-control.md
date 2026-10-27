# Z2M turn_on_for: turn on Hue native control so a color timer lights in its color

## Context

A Hue bulb on Z2M, timed with a color from off, lights at its last color first: Zigbee sends on and color as
separate commands, and the bulb drops a color sent while off. Plain HA `light.turn_on` does the same, with or
without `transition: 0`. Watched probes (2026-10-27) found the fix: Z2M's per-device option
`hue_native_control` (zigbee-herdsman-converters `src/lib/philips.ts`) sends on, brightness, color and color
temperature as one Philips-cluster command. With it on, HA's `light.turn_on` and `device_side.turn_on_for`
with a color both lit red from the start, and `on_time` still turned the bulb off by itself, with or without
a color. The adapter needs no change to its calls, only the option on.

Users shouldn't have to find that option and set it on every new Hue bulb, so the adapter turns it on itself
and the README says so.

## Decisions

- **When:** lazily, on the first `turn_on_for` whose fields include a color or color temperature
  (`rgb_color`, `hs_color`, `xy_color`, `color_temp_kelvin`) to a Hue bulb, or a group with a Hue member, that
  has the option off. Lights never timed with those fields are never touched. Brightness alone is already one
  Zigbee command (`moveToLevelWithOnOff`) and doesn't trigger it.
- **Hue only.** Other brands' color bulbs keep today's behavior (untested, documented as lighting at last
  color first).
- **Telling users:** README and `docs/integrations.md`, plus an info-level HA log line per light when the
  adapter turns it on. No repair notice, no opt-out option.
- **No reply:** the adapter waits a few seconds for Z2M's "ok". On timeout or error it logs a warning and sends
  the timer as today. This one call may light at the last color first; the result stays `sent`, and the next
  call checks again.
- **Groups: the group's own option.** A command to a group reads the group's options, never its members'
  (Z2M `lib/extension/publish.ts`), so the adapter sets `hue_native_control` on the group when a member is a
  Hue bulb.

## Group probe (2026-10-27)

A temporary Z2M group of one Hue color bulb, timed red from warm white and off:

| Option set on | Command Z2M sent | Seen |
|---|---|---|
| nothing | standard on, then color | (known from the single-bulb probe: last color first) |
| the member | standard: Z2M ignores member options for a group | not watched; ruled out by source |
| the group | Philips native (`effect` in the group's state) | red from the start, timer off by itself |

A group whose members can't all show color has no color mode in HA (Z2M exposes the members' common features),
so a mixed white and color group takes no color call at all.

With the group option on, the bulb reported itself on at its old color temperature about a second after the
call, while it showed red. HA may show the old color for the timer's first seconds. The rig run checks whether
a single bulb does the same.

## Facts the design rests on (verified in source or live)

- Z2M publishes `zigbee2mqtt/bridge/info` retained, with `config` = its settings, so `config.devices[<ieee>]`
  and `config.groups[<id>]` hold each entity's options, `hue_native_control` among them.
- `zigbee2mqtt/bridge/request/{device,group}/options` with `{"id", "options", "transaction"}` answers on
  `zigbee2mqtt/bridge/response/{device,group}/options` with `status` and the same `transaction`.
- HA's device registry shows a Hue bulb on Z2M with manufacturer `Philips` (Z2M's vendor string).
- Group members live outside `bridge/info`; `zigbee2mqtt/bridge/groups` (retained) lists them by IEEE.

## Steps

1. **`integrations/zigbee2mqtt/native_control.py`** (new; imported by `turn_on_for.py`, so it joins the
   adapter's fingerprint): `ensure_native_control(hass, target)` reads `bridge/info` per call (no cache, so a
   user who turns it off is seen), sets the option when it's off, and never raises into the call. A device
   qualifies by its manufacturer; a group by its members' (from `bridge/groups`).
2. **`turn_on_for.py`**: call it before `light.turn_on` when the fields include a color or color temperature.
3. **Tests**: a fake broker for subscribe and the options request. Hue device off/on, not Hue,
   brightness-only, no `bridge/info`, no reply, error reply, transaction matching, group with and without a
   Hue member. Adapter module coverage stays at 95% or above.
4. **Docs**: `docs/integrations.md` (why, what changes for the bulb outside Device Side, how to turn it back
   off, groups), a sharp edge for other brands' color bulbs, and a README line.
5. **Rig**: an admin-only setup step that sets a Z2M device option on the case's light, so the rig proves the
   adapter turns it on; `zigbee2mqtt` joins `ADMIN_INTEGRATIONS`. The rig's Z2M group has no Hue member, so
   the group path needs a tester report for beta.

## Verification

- `.venv/bin/pytest`, `pre-commit run --all-files`, `/audit-code` on the diff, PR into the release branch.
- A watched rig run of the Z2M cases: color red from the start with the option turned on by the adapter,
  every timer off by itself. A full pass writes `docs/bench/zigbee2mqtt/turn_on_for.md`.

# Slice 13a: Zigbee probe findings

Answers the five questions in `2026-10-27-zigbee-parity-timer-state.md` (13a) before any ZHA or Z2M adapter is
written. Three findings bear on the plan's decisions; they are listed first and go back to the maintainer before
13e.

Measured 2026-10-27, unattended, from a scratchpad script: raw ZCL commands through `zha.issue_zigbee_cluster_command`
and Z2M's generic `command` payload, live attribute reads (ZHA's admin read, Z2M's generic `read`), and
timestamped HA `state_changed` and Z2M state messages. Nothing was watched by eye.

| Bulb | Network | Model | Firmware | ColorCapabilities |
|---|---|---|---|---|
| A60 | Z2M | Hue Essential White and Color Ambiance A60 | 1.126.9 | 31: hue/sat, enhanced hue, loop, xy, CT |
| CT bulb | Z2M | Hue white ambiance E27 800lm with Bluetooth | 1.76.11 | 16: CT only |
| LTA004 | ZHA | LTA004 | 0x01001416 | 16: CT only |

The LTA004 is the inventory's ZHA `light_ct`; ZHA's `light_dimmable` is a different bulb. Both Z2M bulbs had
`hue_native_control` on, which raw commands bypass. Every bulb's Level and Color `Options` read 0, so nothing
persistent was set.

## Findings that touch a decision

1. **The LTA004 on ZHA does report brightness, and ZHA applies it.** The code read said Hue bulbs don't report.
   During a raw 6 s `MoveToLevel`, with no reads, HA's brightness changed once a second (45, 80, 115 … 220) and
   ended on the bulb's value. After a raw level `Stop`, HA showed the halted level within 1 s with no
   `update_entity`. Color temperature is never applied: HA stayed on the old value for 20 s after a raw
   `MoveToColorTemp`, until `update_entity` corrected it within 0.5 s.
   *Effect:* the `update_entity` decision stands, since color needs it. For brightness it is redundant on this
   bulb, and mid-move prediction on ZHA matters mainly for color.
2. **After a Z2M hue or saturation stop, HA misses the read-back.** Z2M published the halted color 0.23 s after
   `hue_move: stop`, and it matched the bulb (hue 173° against `CurrentHue` 123/254). It published the color as
   `color_mode: "hs"`, though, and HA has only `color_temp` and `xy` for the A60, so HA kept the pre-move color.
   The plan says Z2M's own stop read-back needs nothing added; that holds for brightness and color temperature
   (below) but not for hue and saturation. 13i needs a decision here.
3. **A raw Z2M `command` updates no state.** Z2M publishes nothing after a generic `command`, so HA keeps what it
   had. After a hue/sat write while off followed by an `On`, HA still showed the old color temperature,
   not the stored hue and saturation. 13j's set while off goes through this path and needs a read-back. A follow-up test on the CT
   bulb (write while off, then a plain HA `light.turn_on`): with no read-back, HA kept the old brightness and
   color temperature after the turn on; with a `/get` of `brightness` and `color_temp` while off, HA showed the
   stored values. One caveat: the probe's own `Off` was a raw command too, so HA believed the bulb was on
   throughout. In real use the off comes through HA, and it is untested whether HA keeps a brightness Z2M
   publishes for a bulb HA shows as off.

## (1) ExecuteIfOff while off

All three bulbs store the value while off when the command carries `options_mask: 1, options_override: 1`, stay
off, and come on at it. Without the override, the same command while off was dropped on every bulb.

| Bulb | Command while off | Without override | With override | After a plain `On` |
|---|---|---|---|---|
| A60 | `MoveToLevel` 40 | stays 199 | 40, still off | 40 |
| A60 | `MoveToColorTemp` 370 | stays 250 | 370, still off | 370 |
| A60 | `MoveToHueAndSaturation` 170/254 | stays 30/59 | 170/254, mode HS, still off | 170/254 |
| CT bulb | `MoveToLevel` 40, `MoveToColorTemp` 370 | unchanged | stored, still off | 40, 370 |
| LTA004 | `MoveToLevel` 40, `MoveToColorTemp` 370 | unchanged | stored, still off | 40, 370 |

"Come on at it" is from attribute reads straight after `On`, not by eye. No bulb needs the
`execute_if_off_unsupported` refusal.

On ZHA (LTA004, write while off, then a plain HA `light.turn_on`): with no refresh, HA came on at the stored
brightness (from the bulb's report) but the old color temperature; with `update_entity` while off, it came on
showing both stored values. This confirms the plan's `update_entity` after a write while off. For Z2M, see
finding 3.

## (2) Stop during a transition

Every stop halted a 10 s `MoveTo…` part-way, and the value held at +0.3 s, +3 s and +9 s (past the transition's
end). Reads mid-transition are live values, not the target (unlike the Hue bridge).

| Bulb | Move | At 1.5 s | Stop at 3 s, held at |
|---|---|---|---|
| A60 | `MoveToLevel` 10 → 254, level `Stop` | 57 | 83 |
| A60 | `MoveToColorTemp` 153 → 447, `StopMoveStep` | 209 | 239 |
| A60 | `MoveToHueAndSaturation` 0/254 → 120/60, `StopMoveStep` | 22/217 | 36/195 |
| A60 | `EnhancedMoveHue` up, rate 6000, `StopMoveStep` | 11623 | 18421 |
| CT bulb | level, then CT, as the A60 | 56, 210 | 82, 243 |
| LTA004 | level, then CT, as the A60 | 49, 201 | 84, 243 |

## (3) State after a stop

- **ZHA:** see finding 1. `update_entity` after a raw stop made HA match the bulb (88 against 88).
- **Z2M brightness:** after `brightness_move: stop`, Z2M published the halted brightness 0.65–0.71 s after the
  stop was published (one stale publish of the old value just before it), and HA followed at once. It matched a
  live read on both bulbs.
- **Z2M color temperature:** after `color_temp_move: stop`, 0.23–0.24 s, matching a live read on both bulbs.
- **Z2M hue:** see finding 2.

Z2M published no state during any move: these bulbs send no reports on Z2M.

## (4) Z2M generic payloads

- **`command`** works: `{"command": {"cluster": "genLevelCtrl", "command": "moveToLevel", "payload": {...}}}`, with
  herdsman's parameter names (`transtime`, `optionsMask`, `optionsOverride`, `colortemp`, `movemode`). Success is
  silent; a failure is an error on `bridge/logging`.
- **`read`** works, including `OnTime`. The result reaches MQTT only through `state_property`, which puts it into
  the device's state under that key (it stays in Z2M's state cache). Z2M's log carries the result at info level,
  and this broker's log topic carried only errors. Replies took 0.04–0.24 s.
- **`OnTime` during a Z2M `on_time: 30` timer:** 280 at 2 s, 249 at 5 s (tenths, counting down), `OffWaitTime` 0,
  and 0 after `turn_off`. So the Z2M timer can be reported (13h).

## (5) ColorCapabilities

In the bulb table above. Only the A60 reports enhanced hue, so it is the only probed bulb that `EnhancedMoveHue`
applies to.

## Incident

During the first run, Z2M's coordinator failed (`ASH_NCP_FATAL_ERROR`) and Z2M restarted itself; firmware updates
were running on the network at the time. The Z2M results from that window were discarded and rerun once no update
was in progress. The probed bulbs' firmware was the same before and after.

# Device Side

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz/) [![Latest Version](https://img.shields.io/github/v/release/jasonmx/device-side?sort=date)](https://github.com/jasonmx/device-side/releases) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/jasonmx)

Device Side unlocks native features in your lights, switches and plugs on the Zigbee, Shelly, Philips Hue and Matter integrations, so you can:

* **Delay a turn-off:** Tell a device to turn off automatically, even if HA goes offline.

* **Dim smoothly:** Press to dim and release to stop, using third-party buttons.
* **Change colors smoothly:** Press to change color, release to stop.
* **Set lights without turning on:** Pre-stage brightness, color, CT and scenes.

Device Side also patches some usability quirks in individual integrations.

## How It Helps You 🔅💡🔆

* **Convenient & reliable:** Replace automations with actions that survive HA restarts.
* **Silky smooth:** Brightness and color transitions are continuous and precise. No more jittery steps or overshoots.
* **Predictable:** Prepare your lights to turn on how you want them, without unsightly color flashes or brightness extremes.
* **Zero setup:** Connects to your devices automatically via the core integrations.

## Features

[List of action names, supported integrations, brief description, and 1-2 example use cases]

Timed on/off: Turn on or off, with a delayed flip back. Flip-back timer runs on the device. Example use cases:

- Cut power to a heater or ironing station after 4 hours of inactivity
- Run a bathroom fan for 20 minutes after a shower.
- Power-cycle a router.

turn_on_for [list the integrations it support]

turn_off_for [list the integrations it support]

Smooth Dimming & Color Transitions

Create polished “press to dim or change color, release to stop" automations. Transitions run natively on the device, with one command to start and a second to stop.

raise_brightness [list the integrations it support]

raise_hue

raise_saturation

lower_brightness [list the integrations it support]

lower_hue

lower_saturation

stop

Set Lights Without Turning On

Set scenes, brightness, color and color temperature while the lights are off, so that they turn on smoothly without unsightly color or brightness flashes.

set_attributes

set_scene

Get Attributes

Read device attributes that aren't exposed reliably by Home Assistant. Example use cases:

* Check a device's on/off timer.

* Check a light's brightness, color or color temperature while it's off or transitioning.

get_attributes

Usability patches

* Zigbee2MQTT lights now report color after hue/saturation commands.

* ZHA optimistic turn-off...

* Hue Bridge optimistic transition...

[get Claude to check for others]

|                        | Shelly                                     | Zigbee2MQTT | ZHA | Matter                  | Hue |
|:---------------------- |:------------------------------------------:|:-----------:|:---:|:-----------------------:|:---:|
| On With Timed Off      | ✅ switches, color bulbs<br>🙋 other lights |             |     | ✅ switches<br>🙋 lights | ❌   |
| Off With Timed On      | ✅ switches, color bulbs<br>🙋 other lights | ❌           | ❌   | ❌                       | ❌   |
| Smooth Dimming         |                                            |             |     |                         | ✅¹  |
| Read Timer and Color   | ✅ switches, color bulbs<br>🙋 other lights |             |     | ✅ switches<br>🙋 lights |     |
| Set Without Turning On |                                            |             |     |                         | ✅¹  |

✅ Stable · 🙋 Ready for release once a [volunteer tests it](CONTRIBUTING.md) · ❌ Appears not possible

¹ Available now in [Hue Smooth Dimming](https://github.com/jasonmx/hue-smooth-dimming).

Details per integration are in [docs/integrations.md](docs/integrations.md), including the Zigbee2MQTT options Device Side sets on your devices. Shelly Gen 1, Hue Bridge v1, and Zigbee plugs and switches are unsupported.

During a Hue fade, Home Assistant shows the brightness Device Side predicts, rather than the end value the bridge reports as the fade starts. This is on by default; turn it off in Device Side's options.

On Zigbee2MQTT, Device Side fixes Home Assistant showing the wrong color for full-color bulbs, by [announcing both of their color modes](docs/integrations.md#what-device-side-changes-in-zigbee2mqtt). This is on by default; turn it off in Device Side's options.

**Disclaimer:** Some devices pretend to support these features (they accept the commands but don't implement the behaviors). Test each of your devices with the Device Side actions before relying on device-native features.

## Get Started

### Requirements

* At least one of [ZHA](https://www.home-assistant.io/integrations/zha/), [Z2M](https://www.zigbee2mqtt.io) via [MQTT](https://www.home-assistant.io/integrations/mqtt/), [Shelly](https://www.home-assistant.io/integrations/shelly/), [Philips Hue](https://www.home-assistant.io/integrations/hue) or [Matter](https://www.home-assistant.io/integrations/matter/) integrations installed.

* Not supported: Hue Bridge v1, Shelly Gen1

### Install from HACS

<details>
<summary>Show me how</summary>

1. Open the Device Side HACS repository

   [![Open the Device Side HACS repository in your Home Assistant instance.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jasonmx&repository=device-side&category=integration)

2. Click **Download**

3. Restart Home Assistant

4. Add the integration

   [![Add Device Side to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=device_side)

</details>

## Usage

### Timed on/off

Timer runs on the device. Use it to:

- Cut power to a heater or ironing station after 4 hours, in case someone forgets to turn it off.
- Run a bathroom fan for 20 minutes after a shower.
- Power-cycle your router via a smart plug.

| Action                     | Description                                     |
|:-------------------------- |:----------------------------------------------- |
| `device_side.turn_on_for`  | Turns on, then off automatically after a delay. |
| `device_side.turn_off_for` | Turns off, then on automatically after a delay. |

| Field               | Actions     | Description                                                                                                           |
|:------------------- |:----------- |:--------------------------------------------------------------------------------------------------------------------- |
| `target`            | all         | Lights and switches (required)                                                                                        |
| `duration`          | all         | How long until the device toggles, 50 ms to 7 days (required)                                                         |
| `brightness`        | turn_on_for | Brightness (1–255). 🔒                                                                                                |
| `color_temp_kelvin` | turn_on_for | Color temperature (2000–6500 K). 🔒                                                                                   |
| `rgb_color`         | turn_on_for | Color as `[red, green, blue]` (0–255 each). 🔒                                                                        |
| `hs_color`          | turn_on_for | Color as `[hue, saturation]` (0–360, 0–100). 🔒                                                                       |
| `xy_color`          | turn_on_for | Color as `[x, y]`. 🔒                                                                                                 |
| `transition`        | turn_on_for | Fade time (0–300 s). 🔒                                                                                               |
| `response_variable` | all         | Name of a variable that receives a result for each entity (optional). In the visual editor it's **Response variable** |

A field marked 🔒 is refused in the release, as it's awaiting testing on real hardware. You can test it for us: see [CONTRIBUTING.md](CONTRIBUTING.md).

**Cancel:** to cancel a timer, send a new action (e.g. `turn_on`, `turn_off`, `toggle` or a new timed on/off).
On ZHA, only `turn_off` or a new `turn_on_for` cancels; to keep the light on, turn it off, then on.

#### Results

Each targeted entity gets a `status` in the response variable:

| Status      | Meaning                                            |
| ----------- | -------------------------------------------------- |
| `confirmed` | Command accepted; device reported a running timer  |
| `sent`      | Command accepted; timer not confirmed in read-back |
| `unchanged` | Nothing to send; `detail` says why                 |

If a requested duration is out of range, `clamped_to` reports the duration the device actually used, in seconds. A field the entity can't take, like brightness on a plug, is dropped and the rest of the call goes ahead, with `detail: fields_dropped`.

Failures follow Home Assistant's own actions. The action fails, stopping the automation, if an entity you listed by name can't take it (the error says why) or if a device fails (every entity is still sent the command first, and the error lists the ones that failed). An entity reached through an area, device, label or group that can't take the action is skipped and logged, and unavailable entities are skipped. Skipped entities are left out of the response.

#### YAML Example: Heater off after 4 hours, with a warning

```yaml
actions:
  - action: device_side.turn_on_for
    target:
      entity_id: switch.heater
    data:
      duration: "04:00:00"
    response_variable: result
  - if: "{{ result['switch.heater'].status != 'confirmed' }}"
    then:
      - action: notify.notify
        data:
          message: "Heater timer not confirmed: {{ result['switch.heater'].status }}"
```

***

## Uninstall

This integration follows standard integration removal.

1. Open the integration

[![Open the Hue Smooth Dimming integration in your Home Assistant instance.](https://my.home-assistant.io/badges/integration.svg)](https://my.home-assistant.io/redirect/integration/?domain=device_side)

2. Open the ⋮ menu and choose **Delete**

# Device Side

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz/) [![Latest Version](https://img.shields.io/github/v/release/jasonmx/device-side?sort=date)](https://github.com/jasonmx/device-side/releases) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/jasonmx)

Device Side unlocks popular on-device features for lights and switches, like timed on/off, via Matter, Zigbee, Shelly or Hue. Device-side features run natively on your lights and switches, so survive HA restarts.

It also extends Home Assistant's shared light model. It lets you read a light's attributes while it's off, keeps brightness and color temperature accurate when you stop a transition partway, and handles protocol-specific quirks found in testing on real hardware.

**Disclaimers:**

1. **Compatibility warning:** Some device makes and models act on commands but don't acknowledge them, and some acknowledge but don't act. Test each of your devices with Device Side before relying on its features.

2. **AI-assisted coding:** I code with AI. I've designed, coded and built products for 35 years, so have a rough idea what I'm doing. All code changes are tested on real devices before release.

If you're OK with that, let's dive in.

## Feature Availability

|                        |         Shelly          | Zigbee2MQTT | ZHA | Matter | Hue |
|:---------------------- |:-----------------------:|:-----------:|:---:|:------:|:---:|
| On With Timed Off      | ✅ switches<br>🙋 lights |          |   |      | ❌ |
| Off With Timed On      | ✅ switches<br>🙋 lights |     ❌      | ❌  |   ❌   | ❌ |
| Smooth Dimming         |                         |           |   |      | ✅¹ |
| Set Without Turning On |                         |           |   |      | ✅¹ |

✅ Stable · 🙋 Ready for release once a [volunteer tests it](CONTRIBUTING.md) · ❌ Appears not possible

¹ Available now in [Hue Smooth Dimming](https://github.com/jasonmx/hue-smooth-dimming).

Details per integration are in [docs/integrations.md](docs/integrations.md), including the Zigbee2MQTT option Device Side turns on for Hue bulbs timed with a color. Shelly Gen 1, Hue Bridge v1, and Zigbee plugs and switches are unsupported.

## Get Started
Requires at least one core integration to be installed: Matter, ZHA, Z2M via MQTT, Shelly, or Philips Hue.

<details>
<summary>Install from HACS</summary>

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
| `duration`          | all         | How long until the device toggles, 50 ms to 7 days (required)                                                      |
| `brightness`        | turn_on_for | Brightness (1–255). 🔒                                                                                                |
| `color_temp_kelvin` | turn_on_for | Color temperature (2000–6500 K). 🔒                                                                                   |
| `rgb_color`         | turn_on_for | Color as `[red, green, blue]` (0–255 each). 🔒                                                                        |
| `hs_color`          | turn_on_for | Color as `[hue, saturation]` (0–360, 0–100). 🔒                                                                       |
| `xy_color`          | turn_on_for | Color as `[x, y]`. 🔒                                                                                                 |
| `transition`        | turn_on_for | Fade time (0–300 s). 🔒                                                                                               |
| `response_variable` | all         | Name of a variable that receives a result for each entity (optional). In the visual editor it's **Response variable** |

A field marked 🔒 is `unsupported` in the release, as it's awaiting testing on real hardware. You can test it for us: see [CONTRIBUTING.md](CONTRIBUTING.md).

**Cancel:** to cancel a timer, send a new action (e.g. `turn_on`, `turn_off`, `toggle` or a new timed on/off).
On ZHA, only `turn_off` or a new `turn_on_for` cancels; to keep the light on, turn it off, then on.

#### Results

Each targeted entity gets a `status` in the response variable:

| Status        | Meaning                                            |
| ------------- | -------------------------------------------------- |
| `confirmed`   | Command accepted; device reported a running timer  |
| `sent`        | Command accepted; timer not confirmed in read-back |
| `unsupported` | Entity or field not supported; `detail` says why   |
| `rejected`    | Command failed; `detail` says why                  |

If a requested duration is out of range, `clamped_to` reports the duration the device actually used, in seconds.

The action succeeds if at least one entity returns `confirmed` or `sent`. If every entity returns `unsupported` or `rejected`, the action fails instead: no response is returned, and the automation stops there, like any failed action. The error message lists each entity with its reason.

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

# Device Side

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz/) [![Latest Version](https://img.shields.io/github/v/release/jasonmx/device-side?sort=date)](https://github.com/jasonmx/device-side/releases) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://www.buymeacoffee.com/jasonmx)

Device Side unlocks popular on-device features for lights and switches, like on-with-timed-off, via the Matter, Zigbee, Shelly and Hue integrations. Device-side features are more reliable than HA automations, as they run natively on the device and survive HA restarts.

**Disclaimers:**

1. **Device compatibility:** Some device makes and models act on commands but don't acknowledge them, and some acknowledge but don't act. Test Device Side's actions on your own devices before relying on them.

2. **AI-assisted coding:** I code with AI. I've designed, coded and built products for 35 years, so have a rough idea what I'm doing. Every feature is only released after testing on real hardware.

If you're OK with these, let's dive in!

# Get Started

### Install from HACS

1. Open the Device Side HACS repository

   [![Open the Device Side HACS repository in your Home Assistant instance.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jasonmx&repository=device-side&category=integration)

2. Click **Download**
3. Restart Home Assistant
4. Add the integration

   [![Add Device Side to your Home Assistant instance.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=device_side)

# Feature Availability

|                        |         Shelly          | Zigbee2MQTT | ZHA | Matter | Hue |
|:---------------------- |:-----------------------:|:-----------:|:---:|:------:|:---:|
| On With Timed Off      | ✨ switches<br>🙋 lights |     🔵      | 🔵  |   🔵   | 🔵  |
| Off With Timed On      | ✨ switches<br>🙋 lights |     ❌      | ❌  |   ❌   | 🔵  |
| Smooth Dimming         |           🔵            |     🔵      | 🔵  |   🔵   | ✅¹ |
| Set Without Turning On |           🔵            |     🔵      | 🔵  |   🔵   | ✅¹ |

✨ New, tested on real hardware · ✅ Stable · 🙋 Needs a volunteer to test it
([help test](CONTRIBUTING.md)) · 🔵 Roadmap · ❌ Appears not possible

¹ Available now in [Hue Smooth Dimming](https://github.com/jasonmx/hue-smooth-dimming), and moving into Device Side.

Details per integration are in [docs/integrations.md](docs/integrations.md).

# Usage

## Timed on/off

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
| `duration`          | all         | How long until the device flips back, 50 ms to 7 days (required)                                                      |
| `brightness`        | turn_on_for | Brightness (1–255). 🔒                                                                                                |
| `color_temp_kelvin` | turn_on_for | Color temperature (2000–6500 K). 🔒                                                                                   |
| `rgb_color`         | turn_on_for | Color as `[red, green, blue]` (0–255 each). 🔒                                                                        |
| `hs_color`          | turn_on_for | Color as `[hue, saturation]` (0–360, 0–100). 🔒                                                                       |
| `xy_color`          | turn_on_for | Color as `[x, y]`. 🔒                                                                                                 |
| `transition`        | turn_on_for | Fade time (0–300 s). 🔒                                                                                               |
| `response_variable` | all         | Name of a variable that receives a result for each entity (optional). In the visual editor it's **Response variable** |

A field marked 🔒 is `unsupported` in the release, as it's awaiting testing on real hardware. You can test it for us: see [CONTRIBUTING.md](CONTRIBUTING.md).

**Cancel:** to cancel a timer, send a `turn_on`, `turn_off`, `toggle` or new timed on/off command.

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

##### YAML Example: Heater off after 4 hours, with a warning

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

# License

MIT

# Device Side

Home Assistant actions for light and switch features your devices already have but Home Assistant
doesn't expose.

Many devices can run a timer, dim smoothly or store a color while off. Home Assistant Core leaves
these out because it can't guarantee them: a device may not say whether it supports a command, or
whether it acted on it. Device Side lets you take that risk, and tells you per entity what
happened.

## Actions

| Action | What it does |
|---|---|
| `device_side.turn_on_for` | Turns on, then the device turns itself off after `duration`. |
| `device_side.turn_off_for` | Turns off, then the device turns itself back on after `duration`. |

The timer runs on the device, so it still finishes if Home Assistant restarts or goes offline.

```yaml
action: device_side.turn_on_for
target:
  entity_id: switch.porch
data:
  duration: "00:05:00"
response_variable: result
```

## Results

Each targeted entity gets a status in the response:

| Status | Meaning |
|---|---|
| `confirmed` | The device accepted the command and reported it running. |
| `sent` | The device accepted the command but didn't confirm it. |
| `unsupported` | Not sent: this entity or field isn't supported. `detail` says why. |
| `rejected` | Sent, but the device or its integration returned an error. |

The action raises an error only when no entity accepted the command.

## Support

<!-- matrix:start -->
| Platform | Targets | `turn_on_for` | `turn_off_for` |
|---|---|---|---|
| Shelly Gen2+ | relays, as a `switch` or an on/off `light` | beta | beta |
<!-- matrix:end -->

Beta means tested on real hardware. Shelly dimmers and color lights aren't supported yet because
nobody has tested them. Details per platform are in [docs/platforms.md](docs/platforms.md).

A switch shown as a light with the "Change device type of a switch" helper (`switch_as_x`) is
served as the switch it wraps. Inverted helpers are not supported.

## Install

1. In HACS, open the menu, choose **Custom repositories**, and add
   `https://github.com/jasonmx/device-side` as an **Integration**.
2. Download **Device Side** and restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration** and add **Device Side**.

## Principles

- **Fill gaps, don't copy Core.** A Core feature is redone only to fix a sharp edge or make it much
  easier to use.
- **Popular features only.** A feature needs an integration on over 20% of installs that can back
  it, and more than one person asking for it.
- **Built for people, not a passthrough.** Actions take what you think in (a dim speed), not the
  device's raw parameters (a distance and a duration).
- **Tested on real hardware.** Mocks miss what devices really do, such as clamping or rounding
  values. Anyone can test an adapter on their own setup, and a passing report counts.
- **Open to contributors.** Each feature runs on each platform through its own adapter, so new
  devices and features can be added one adapter at a time.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT

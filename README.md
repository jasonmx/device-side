# Device Side

Home Assistant actions for the light and switch features your devices already support but Home
Assistant leaves out: turn on for a set time, turn off for a set time, smooth hold-to-dim, and
setting brightness or color while a light is off.

Each feature comes from one or more actions that work across integrations. The command runs on
the device or bridge itself, so a timer started by Device Side still finishes if Home Assistant
restarts or goes offline.

> **Status:** early development. Nothing here is ready to install yet.

## Supported integrations

Zigbee2MQTT, ZHA, Matter, Shelly Gen2+ and Philips Hue (bridge v2). What each action does on
each integration, and how mature that support is, is listed in the matrix below.

A switch shown as a light with the "Change device type of a switch" helper (`switch_as_x`) is
served as the switch it wraps, and results are reported under the light's name. Inverted wrappers
are not supported.

## Support matrix

<!-- matrix:start -->
_Generated from the code. No adapters yet._
<!-- matrix:end -->

## License

MIT

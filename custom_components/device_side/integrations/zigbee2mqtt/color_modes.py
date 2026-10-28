"""Announce Z2M's full-color lights to Home Assistant with both color modes, so HA takes their state in either.

Z2M's discovery gives a light that exposes both `color_xy` and `color_hs` only one of the two modes (lib/extension/
homeassistant.ts, `colorModes`). Whenever the bulb is in the other one (after a hue or saturation move, a Hue scene,
a remote's binding or a power cut), Z2M's state says so and HA drops it as an invalid color mode, keeping the old
color (Koenkk/zigbee2mqtt#28757; upstream declined to announce both, #33025). Z2M applies a device's or group's
`homeassistant.light` options over its discovery message last, so setting `supported_color_modes` there to both
modes fixes it in HA without touching the bulb.

Z2M's options API can't delete a key under `homeassistant`: a null there is kept, and means "strip this from the
discovery message" (for `light`, "don't announce the light"). So turning the option off writes back the modes Z2M
announces by itself, which leaves HA as it would be without device_side. Either of those two values is device_side's
own; any other value is the user's and is left alone.
"""

import logging
from collections.abc import Callable
from functools import partial

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.debounce import Debouncer

from .addressing import bridge_topic
from .bridge import ensure_options, retained

_LOGGER = logging.getLogger(__name__)

# Z2M republishes bridge/devices when a device joins, is interviewed, announces itself or is renamed, and
# bridge/groups when a group or its members change (lib/extension/bridge.ts); an options change republishes neither.
_WATCHED = ("devices", "groups")
# Z2M publishes devices, then groups, then more for one change: one pass after they settle.
_SETTLE_S = 2.0


def light_expose(definition: dict | None) -> dict | None:
    """A device definition's light expose, or None when it has none or several (one per endpoint).

    A light on an endpoint is announced as `light_<endpoint>`, which takes its own options key; those are left out.
    """
    lights = [e for e in (definition or {}).get("exposes", []) if e.get("type") == "light"]
    if len(lights) != 1 or lights[0].get("endpoint"):
        return None
    return lights[0]


def _features(expose: dict) -> list[str]:
    return [feature.get("name") for feature in expose.get("features", [])]


def qualifies(expose: dict | None) -> bool:
    """True for a light that exposes both color models, which Z2M announces with only one."""
    return expose is not None and {"color_hs", "color_xy"} <= set(_features(expose))


def both_modes(exposes: list[dict]) -> list[str]:
    """What device_side announces: both color modes, and color temperature where Z2M would announce it."""
    return ["xy", "hs"] + (["color_temp"] if any("color_temp" in _features(e) for e in exposes) else [])


def default_modes(exposes: list[dict]) -> list[str]:
    """The modes Z2M announces by itself for these lights' exposes, computed as its discovery does.

    It picks hs over xy when any light lists `color_hs` before `color_xy`.
    """
    features = [_features(e) for e in exposes]
    prefer_hs = any(
        "color_xy" in names and "color_hs" in names and names.index("color_hs") < names.index("color_xy")
        for names in features
    )
    has = {name for names in features for name in names}
    modes = []
    if "color_xy" in has and not prefer_hs:
        modes.append("xy")
    if "color_hs" in has and ("color_xy" not in has or prefer_hs):
        modes.append("hs")
    if "color_temp" in has:
        modes.append("color_temp")
    return modes


def wanted(current: dict, exposes: list[dict], enabled: bool) -> dict:
    """The options to send for an entity with `current` options, or none when they already hold what they should.

    A device or light excluded from discovery (its key set to null) is left alone, as is a user's own value.
    """
    if "homeassistant" in current and not isinstance(current["homeassistant"], dict):
        return {}
    light = (current.get("homeassistant") or {}).get("light", {})
    if not isinstance(light, dict):
        return {}
    on, off = both_modes(exposes), default_modes(exposes)
    modes = light.get("supported_color_modes")
    if "supported_color_modes" in light and not (_same(modes, on) or _same(modes, off)):
        return {}
    target = on if enabled else off
    if _same(modes, target) or (not enabled and "supported_color_modes" not in light):
        return {}
    return {"homeassistant": {"light": {"supported_color_modes": target}}}


def _same(modes: object, ours: list[str]) -> bool:
    return isinstance(modes, list) and sorted(modes) == sorted(ours)


async def ensure_color_modes(hass: HomeAssistant, enabled: bool) -> None:
    """Announce each qualifying light and group with both modes when enabled, or put back Z2M's own when not.

    A group qualifies when every member does. Never raises: with no Z2M it does nothing, and a light it can't change
    is logged and left as it was.
    """
    try:
        devices = await retained(hass, "devices")
        groups = await retained(hass, "groups")
        settings = (await retained(hass, "info")).get("config", {})
        entities = _entities(devices, groups)
    except TimeoutError as err:
        _LOGGER.debug("Not checking Zigbee2MQTT's color modes: %s", err)
        return
    except Exception as err:  # noqa: BLE001 - a background pass; HA keeps announcing what Z2M announced
        _LOGGER.warning("Couldn't read Zigbee2MQTT's devices to check their color modes: %s", err)
        return

    for kind, z2m_id, exposes, name in entities:
        if not wanted(settings.get(f"{kind}s", {}).get(z2m_id, {}), exposes, enabled):
            continue
        modes = both_modes(exposes) if enabled else default_modes(exposes)

        def changed(_z2m_id: str, name: str = name, modes: list[str] = modes) -> None:
            _LOGGER.info(
                "Set Zigbee2MQTT's Home Assistant color modes for %s to %s%s",
                name,
                ", ".join(modes),
                ", so Home Assistant shows its color in either mode" if enabled else ", as Zigbee2MQTT announces it",
            )

        try:
            await ensure_options(hass, kind, [z2m_id], lambda current, e=exposes: wanted(current, e, enabled), changed)
        except Exception as err:  # noqa: BLE001 - one light that can't be changed mustn't stop the others
            _LOGGER.warning("Couldn't set Zigbee2MQTT's Home Assistant color modes for %s: %s", name, err)


def _entities(devices: list[dict], groups: list[dict]) -> list[tuple[str, str, list[dict], str]]:
    """(kind, Z2M ID, light exposes, name) for each qualifying device, and each group whose members all qualify."""
    lights = {
        device["ieee_address"]: expose
        for device in devices
        if qualifies(expose := light_expose(device.get("definition"))) and device.get("ieee_address")
    }
    names = {device.get("ieee_address"): device.get("friendly_name") for device in devices}
    entities = [("device", ieee, [expose], names[ieee]) for ieee, expose in lights.items()]
    for group in groups:
        members = [member.get("ieee_address") for member in group.get("members", [])]
        if members and all(member in lights for member in members):
            entities.append(("group", str(group.get("id")), [lights[m] for m in members], group.get("friendly_name")))
    return entities


async def async_watch(hass: HomeAssistant) -> Callable[[], None]:
    """Run the enabled pass now and whenever Z2M announces a device or group change; returns the unsubscribe.

    The retained messages each subscription gets at once start the first pass.
    """
    debouncer = Debouncer(
        hass,
        _LOGGER,
        cooldown=_SETTLE_S,
        immediate=False,
        function=partial(ensure_color_modes, hass, True),
        background=True,
    )

    @callback
    def announced(_msg: mqtt.ReceiveMessage) -> None:
        debouncer.async_schedule_call()

    unsubscribes = [await mqtt.async_subscribe(hass, bridge_topic(suffix), announced) for suffix in _WATCHED]

    @callback
    def stop() -> None:
        for unsubscribe in unsubscribes:
            unsubscribe()
        debouncer.async_shutdown()

    return stop


async def async_setup(hass: HomeAssistant, entry: ConfigEntry, enabled: bool) -> None:
    """When MQTT is set up: watch Z2M if enabled, or put back Z2M's own color modes once if not.

    Runs as the entry's background task, so it never holds setup back. Unloading never removes anything: it also
    runs at HA's shutdown.
    """
    if not await mqtt.async_wait_for_mqtt_client(hass):
        return
    if enabled:
        entry.async_on_unload(await async_watch(hass))
    else:
        await ensure_color_modes(hass, False)


async def async_remove(hass: HomeAssistant) -> None:
    """Put back Z2M's own color modes, as device_side is deleted."""
    if await mqtt.async_wait_for_mqtt_client(hass):
        await ensure_color_modes(hass, False)

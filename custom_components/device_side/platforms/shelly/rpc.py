"""One <Component>.Set with a flip-back timer, then a GetStatus read-back."""

import logging
from typing import Any

from homeassistant.core import State

from .addressing import address, rpc_device
from ...core.adapter import Adapter
from ...core.capabilities import DurationLimits
from ...core.models import EntityResult, LightFields, Status, Target

_LOGGER = logging.getLogger(__name__)

# The device's own bounds (Switch.Set error -103: "should be > 0 and <= 604800"); it keeps 0.01 s steps.
# Durations arrive rounded to 10 ms and floored at 50 ms (core/duration.py), so only the ceiling can bite here.
TIMER_LIMITS = DurationLimits(min_s=0, max_s=604800)

# Core's floor for an RPC transition (shelly/const.py RPC_MIN_TRANSITION_TIME_SEC).
_MIN_TRANSITION_S = 0.5


def light_params(light: LightFields, component: str, state: State | None) -> dict[str, Any]:
    """light.turn_on fields as <Component>.Set params, translated as shelly/light.py does."""
    params: dict[str, Any] = {}
    if light.brightness is not None:
        params["brightness"] = int(100 * (light.brightness + 1) / 255)
    if light.transition is not None:
        params["transition_duration"] = max(light.transition, _MIN_TRANSITION_S)
    if light.color_temp_kelvin is not None:
        kelvin = light.color_temp_kelvin
        if state is not None:
            low = state.attributes.get("min_color_temp_kelvin", kelvin)
            high = state.attributes.get("max_color_temp_kelvin", kelvin)
            kelvin = min(max(kelvin, low), high)
        params["ct"] = kelvin
    if light.rgb_color is not None:
        params["rgb"] = list(light.rgb_color)
    if component == "RGBCCT" and ("ct" in params or "rgb" in params):
        params["mode"] = "cct" if "ct" in params else "rgb"
    return params


async def set_with_timer(adapter: Adapter, target: Target, params: dict[str, Any]) -> EntityResult:
    """Send the Set (an error propagates, so gather() reports it rejected), then confirm the timer is running.

    A failed or inconclusive read-back still reports SENT: the device accepted the Set.
    """
    device, rpc = rpc_device(target), address(target)
    await device.call_rpc(f"{rpc.component}.Set", {"id": rpc.id, **params})
    try:
        status = await device.call_rpc(f"{rpc.component}.GetStatus", {"id": rpc.id})
    except Exception as err:  # noqa: BLE001 - aioshelly's errors can't be imported here; see addressing.py
        _LOGGER.debug("%s read-back failed for %s: %s", adapter.feature, target.entity_id, err)
        return adapter.result(target, Status.SENT, detail="readback_failed")
    if status.get("output") is params["on"] and "timer_duration" in status:
        return adapter.result(target, Status.CONFIRMED)
    return adapter.result(target, Status.SENT, detail="timer_not_reported")

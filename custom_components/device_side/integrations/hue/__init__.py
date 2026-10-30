"""Philips Hue, through aiohue's v2 API on the core hue integration's bridge."""

from .bridge import expand_group, is_hue_group
from .get_attributes import HueGetAttributes
from .lower_brightness import HueLowerBrightness
from .raise_brightness import HueRaiseBrightness
from .set_attributes import HueSetAttributes
from .set_scene import HueSetScene
from .stop import HueStop
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="hue",
    title="Hue",
    ha_domain="hue",
    is_group=is_hue_group,
    expand_group=expand_group,
    # aiohue allows 3 requests at once per bridge, shared with the core hue integration.
    max_concurrency=2,
)

ADAPTERS = [
    HueGetAttributes,
    HueLowerBrightness,
    HueRaiseBrightness,
    HueSetAttributes,
    HueSetScene,
    HueStop,
]

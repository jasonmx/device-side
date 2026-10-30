"""ZHA, through the core zha integration's cluster command action and its gateway's attribute reads."""

from .addressing import is_zha_group
from .get_attributes import ZHAGetAttributes
from .groups import expand_group
from .lower_brightness import ZHALowerBrightness
from .lower_hue import ZHALowerHue
from .lower_saturation import ZHALowerSaturation
from .raise_brightness import ZHARaiseBrightness
from .raise_hue import ZHARaiseHue
from .raise_saturation import ZHARaiseSaturation
from .set_attributes import ZHASetAttributes
from .stop import ZHAStop
from .turn_on_for import ZHATurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="zha",
    title="ZHA",
    ha_domain="zha",
    is_group=is_zha_group,
    expand_group=expand_group,
    max_concurrency=2,
)

ADAPTERS = [
    ZHAGetAttributes,
    ZHALowerBrightness,
    ZHALowerHue,
    ZHALowerSaturation,
    ZHARaiseBrightness,
    ZHARaiseHue,
    ZHARaiseSaturation,
    ZHASetAttributes,
    ZHAStop,
    ZHATurnOnFor,
]

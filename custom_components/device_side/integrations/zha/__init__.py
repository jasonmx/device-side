"""ZHA, through the core zha integration's cluster command action and its gateway's attribute reads."""

from .addressing import is_zha_group
from .get_attributes import ZHAGetAttributes
from .groups import expand_group
from .move import ZHAMove
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

ADAPTERS = [ZHAGetAttributes, ZHAMove, ZHASetAttributes, ZHAStop, ZHATurnOnFor]

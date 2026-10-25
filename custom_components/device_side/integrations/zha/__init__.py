"""ZHA, through the core zha integration's cluster command action."""

from .addressing import is_zha_group
from .turn_on_for import ZHATurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="zha",
    title="ZHA",
    ha_domain="zha",
    is_group=is_zha_group,
    max_concurrency=2,
)

ADAPTERS = [ZHATurnOnFor]

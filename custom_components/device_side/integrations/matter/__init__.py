"""Matter over the core matter integration's connection to python-matter-server."""

from .get_attributes import MatterGetAttributes
from .turn_on_for import MatterTurnOnFor
from ...core.scope import IntegrationInfo

INTEGRATION = IntegrationInfo(
    key="matter",
    title="Matter",
    ha_domain="matter",
    max_concurrency=2,
)

ADAPTERS = [MatterGetAttributes, MatterTurnOnFor]

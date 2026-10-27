from homeassistant.exceptions import ServiceNotSupported, ServiceValidationError

from ..const import DOMAIN


class TargetNotSupported(ServiceNotSupported):
    """A target the caller named can never take the action: core's ServiceNotSupported, with our reason in it."""

    def __init__(self, entity_id: str, reason: str) -> None:
        # Skips ServiceNotSupported.__init__, which would set core's own translation key.
        ServiceValidationError.__init__(
            self,
            translation_domain=DOMAIN,
            translation_key="target_not_supported",
            translation_placeholders={"entity_id": entity_id, "reason": reason},
        )
        self.reason = reason

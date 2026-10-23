from dataclasses import replace

from .capabilities import DurationLimits
from .models import TimedRequest


def clamp[RequestT: TimedRequest](request: RequestT, limits: DurationLimits) -> tuple[RequestT, float | None]:
    """Fit a request's duration to a cell's limits.

    Rounding to the device's resolution is silent; clamped_to is set only when the requested value lay outside the
    range, since that is the case a caller needs to know about.
    """
    steps = round(request.duration_s / limits.resolution_s)
    rounded = round(steps * limits.resolution_s, 6)
    fitted = min(max(rounded, limits.min_s), limits.max_s)
    clamped_to = fitted if not limits.min_s <= request.duration_s <= limits.max_s else None
    return replace(request, duration_s=fitted), clamped_to

from dataclasses import replace

from .capabilities import DurationLimits
from .models import TimedRequest

# Nothing shorter than 50 ms: a relay can't switch faster, and nobody needs more than 10 Hz.
MIN_DURATION_S = 0.05


def clamp[RequestT: TimedRequest](request: RequestT, limits: DurationLimits | None) -> tuple[RequestT, float | None]:
    """Fit a request's duration to the 50 ms floor and an adapter's limits; a duration in range passes through.

    clamped_to is set only when the requested value lay outside the range, since that is the case a caller needs
    to know about.
    """
    low = max(limits.min_s, MIN_DURATION_S) if limits else MIN_DURATION_S
    fitted = max(request.duration_s, low)
    if limits:
        fitted = min(fitted, limits.max_s)
    clamped_to = fitted if fitted != request.duration_s else None
    return replace(request, duration_s=fitted), clamped_to

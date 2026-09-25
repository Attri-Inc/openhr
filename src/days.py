"""Leave-duration formatting — the single source of truth for rendering durations.

Leave is stored and computed as integer **half-day units** (``UNITS_PER_DAY = 2``),
the same way OpenLedger stores money as integer minor units. A half day is 1 unit,
a full day is 2. This module formats units for display using integer arithmetic
only (divmod), so there is no float rounding anywhere in the project. Every layer
(repositories, seed, reports) must format through `format_units` so a half day
reads identically everywhere.
"""

from src.domain.constants import UNITS_PER_DAY


def format_units(units: int) -> str:
    """Render integer half-day units as a duration string, e.g. 3 -> "1.5 days".

    Uses divmod on integers — never float division — so the result is exact
    regardless of magnitude.
    """
    sign = "-" if units < 0 else ""
    whole, half = divmod(abs(int(units)), UNITS_PER_DAY)
    if half:
        text = f"{whole}.5 days" if whole else "0.5 days"
    else:
        text = "1 day" if whole == 1 else f"{whole} days"
    return sign + text


def days_to_units(days: float | int) -> int:
    """Convert a caller-supplied day count to units, accepting only whole or half days.

    Raises ValueError for anything finer than a half day; callers at the service
    boundary translate that into a ValidationError.
    """
    scaled = float(days) * UNITS_PER_DAY
    units = round(scaled)
    if abs(scaled - units) > 1e-9:
        raise ValueError(f"{days} is not a whole or half day")
    return int(units)

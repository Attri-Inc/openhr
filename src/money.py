"""Money formatting — the single source of truth for rendering amounts.

Compensation (CTC, asset value, offered salary) is stored as integer minor units
(paise). This module formats them using integer arithmetic only (divmod), so
there is no float rounding anywhere in the project.
"""


def format_minor(amount_minor: int) -> str:
    """Render integer minor units (paise) as a currency string, e.g. 4200000000 -> "₹42,000,000.00"."""
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(int(amount_minor)), 100)
    return f"{sign}₹{major:,}.{minor:02d}"


def format_lpa(amount_minor: int) -> str:
    """Render an annual CTC in the lakhs-per-annum shorthand Indian HR uses.

    Integer arithmetic only: one lakh is 10,000,000 paise, so a tenth of a lakh is
    1,000,000 paise. Half-up rounding is done by adding half a divisor before the
    floor division — never float division.
    """
    tenths_of_lakh = (abs(int(amount_minor)) + 500_000) // 1_000_000
    whole, tenth = divmod(tenths_of_lakh, 10)
    sign = "-" if amount_minor < 0 else ""
    return f"{sign}₹{whole}.{tenth} LPA"

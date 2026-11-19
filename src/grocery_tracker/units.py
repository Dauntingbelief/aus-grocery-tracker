"""Parse pack sizes and compute unit prices.

Shelf labels mix units (per 100g, per 1L, per each), which makes products hard to
compare. We normalise every pack to one of three base units so a unit price is
always "$ per kg", "$ per L" or "$ per item".

Accepted pack-size strings (case and spaces don't matter):
    "500g", "1.2kg", "300mL", "2L", "12ea", "1each", "5x72g", "24 x 600mL"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# unit as written -> (base unit, multiplier to convert to base unit)
_UNITS: dict[str, tuple[str, Decimal]] = {
    "g": ("kg", Decimal("0.001")),
    "kg": ("kg", Decimal("1")),
    "ml": ("L", Decimal("0.001")),
    "l": ("L", Decimal("1")),
    "ea": ("each", Decimal("1")),
    "each": ("each", Decimal("1")),
    "pk": ("each", Decimal("1")),
}

_PACK_RE = re.compile(
    r"""^\s*
    (?:(?P<count>\d+)\s*[x×]\s*)?      # optional multipack count, e.g. "24 x"
    (?P<amount>\d+(?:\.\d+)?)\s*       # amount, e.g. "600" or "1.2"
    (?P<unit>[a-zA-Z]+)\s*$            # unit, e.g. "mL"
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class PackSize:
    quantity: float  # total quantity in base_unit
    base_unit: str  # "kg", "L" or "each"


def parse_pack_size(text: str) -> PackSize:
    """Parse a pack-size string into a total quantity in a base unit.

    >>> parse_pack_size("24 x 600mL")
    PackSize(quantity=14.4, base_unit='L')
    """
    match = _PACK_RE.match(str(text))
    if not match:
        raise ValueError(f"Can't parse pack size '{text}'. Expected e.g. '500g', '2L', '6x375mL'.")

    unit_key = match["unit"].lower()
    if unit_key not in _UNITS:
        raise ValueError(f"Unknown unit '{match['unit']}' in pack size '{text}'.")

    base_unit, factor = _UNITS[unit_key]
    count = Decimal(match["count"] or "1")
    amount = Decimal(match["amount"])
    # Decimal avoids float noise like 5 * 0.072 = 0.36000000000000004
    quantity = count * amount * factor
    if quantity <= 0:
        raise ValueError(f"Pack size must be positive, got '{text}'.")
    return PackSize(quantity=float(quantity), base_unit=base_unit)


def unit_price(price: float, pack: PackSize) -> float:
    """Price per base unit ($/kg, $/L or $/each), rounded to 4 decimal places."""
    return round(price / pack.quantity, 4)

"""The contract every price source must meet.

The transform step only ever sees a DataFrame with RAW_COLUMNS. Swapping the hand-typed
CSV for a licensed API later means writing one new class with a `read()` method;
nothing downstream changes.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd

# Canonical raw schema. All values are strings at this stage; the transform parses them.
RAW_COLUMNS: list[str] = [
    "observation_date",  # YYYY-MM-DD the price was seen
    "store",  # anonymised store label, e.g. "store-01"
    "product_id",  # key into data/basket.csv
    "shelf_price",  # price paid today in AUD; blank = not collected
    "promo_type",  # regular | special | price_drop | multibuy (blank = regular)
    "was_price",  # "was" price on a promo ticket, if shown
    "pack_size",  # override if the pack differs from the basket default (shrinkflation)
    "notes",
    "source",  # which PriceSource produced the row
]


class PriceSource(Protocol):
    """Anything that can produce raw price observations."""

    name: str

    def read(self) -> pd.DataFrame:
        """Return observations with exactly RAW_COLUMNS, all as strings."""
        ...

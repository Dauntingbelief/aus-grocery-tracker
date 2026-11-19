"""Shared test fixtures. All prices here are made up for testing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from grocery_tracker.sources.base import RAW_COLUMNS

BASKET_CSV = """product_id,name,brand,category,pack_size
milk-2l,Full Cream Milk,Coles,milk,2L
mince-500g,Beef Mince,Coles,beef_veal,500g
bananas,Bananas (per kg),Loose,fruit,1kg
water-24pk,Spring Water 24 Pack,Coles,soft_drinks_juices,24x600mL
"""


@pytest.fixture
def basket_path(tmp_path: Path) -> Path:
    path = tmp_path / "basket.csv"
    path.write_text(BASKET_CSV)
    return path


@pytest.fixture
def basket(basket_path: Path) -> pd.DataFrame:
    from grocery_tracker.transform import load_basket

    return load_basket(basket_path)


def make_raw(rows: list[dict]) -> pd.DataFrame:
    """Build a raw-schema DataFrame; unspecified fields default to sensible blanks."""
    defaults = {
        "observation_date": "2026-11-22",
        "store": "store-01",
        "product_id": "milk-2l",
        "shelf_price": "3.10",
        "promo_type": "",
        "was_price": "",
        "pack_size": "",
        "notes": "",
        "source": "test",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows], columns=RAW_COLUMNS)

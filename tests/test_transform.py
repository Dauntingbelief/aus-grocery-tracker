import math

import pandas as pd
import pytest
from conftest import make_raw

from grocery_tracker.transform import ValidationError, load_basket, transform, write_parquet


def one(df: pd.DataFrame, product_id: str) -> pd.Series:
    return df.set_index("product_id").loc[product_id]


def test_regular_price_row(basket):
    out = transform(make_raw([{"shelf_price": "3.10"}]), basket).data
    row = one(out, "milk-2l")
    assert row.shelf_price == 3.10
    assert row.regular_price == 3.10
    assert not row.is_promo
    assert row.discount_pct == 0.0
    assert row.unit_price == 1.55  # $3.10 / 2L
    assert row.base_unit == "L"


def test_special_with_was_price(basket):
    raw = make_raw(
        [
            {
                "product_id": "mince-500g",
                "shelf_price": "$5.00",
                "promo_type": "Special",
                "was_price": "8.00",
            }
        ]  # fmt: skip
    )
    row = one(transform(raw, basket).data, "mince-500g")
    assert row.is_promo
    assert row.promo_type == "special"  # lower-cased
    assert row.regular_price == 8.00
    assert row.discount_pct == 0.375  # 1 - 5/8
    assert row.unit_price == 10.0  # $5 / 0.5kg
    assert row.regular_unit_price == 16.0


def test_promo_without_was_price_leaves_regular_unknown(basket):
    raw = make_raw([{"shelf_price": "2.80", "promo_type": "price_drop"}])
    row = one(transform(raw, basket).data, "milk-2l")
    assert row.is_promo
    assert math.isnan(row.regular_price)
    assert math.isnan(row.discount_pct)


def test_blank_shelf_price_rows_are_skipped_not_errors(basket):
    raw = make_raw([{"product_id": "milk-2l"}, {"product_id": "bananas", "shelf_price": ""}])
    result = transform(raw, basket)
    assert list(result.data["product_id"]) == ["milk-2l"]
    assert result.rows_skipped == 1


def test_pack_size_override_flags_shrinkflation(basket):
    raw = make_raw([{"product_id": "mince-500g", "shelf_price": "6.00", "pack_size": "450g"}])
    row = one(transform(raw, basket).data, "mince-500g")
    assert row.pack_size_changed
    assert row.pack_quantity == 0.45
    assert row.unit_price == round(6.00 / 0.45, 4)


def test_pack_size_same_as_default_is_not_flagged(basket):
    raw = make_raw([{"pack_size": "2 l"}])
    assert not one(transform(raw, basket).data, "milk-2l").pack_size_changed


def test_cpi_mapping_and_dates(basket):
    raw = make_raw([{"product_id": "water-24pk", "shelf_price": "7.20"}])
    row = one(transform(raw, basket).data, "water-24pk")
    assert row.cpi_class_code == "115520"
    assert row.cpi_group_code == "131180"
    assert row.cpi_group_name == "Non-alcoholic beverages"
    assert row.year_month == "2026-11"
    assert row.unit_price == 0.5


def test_validation_reports_all_errors_together(basket):
    raw = make_raw(
        [
            {"product_id": "not-in-basket"},
            {"product_id": "bananas", "shelf_price": "-1"},
            {"product_id": "mince-500g", "promo_type": "bogus"},
            {
                "product_id": "water-24pk",
                "promo_type": "special",
                "shelf_price": "9",
                "was_price": "8",
            },  # fmt: skip
        ]
    )
    with pytest.raises(ValidationError) as exc:
        transform(raw, basket)
    messages = "\n".join(exc.value.errors)
    assert len(exc.value.errors) == 4
    assert "not in basket" in messages
    assert "not a positive number" in messages
    assert "promo_type 'bogus'" in messages
    assert "must be above shelf_price" in messages


def test_was_price_on_regular_row_is_an_error(basket):
    with pytest.raises(ValidationError, match="promo_type is 'regular'"):
        transform(make_raw([{"was_price": "4.00"}]), basket)


def test_duplicate_observation_is_an_error(basket):
    with pytest.raises(ValidationError, match="recorded 2 times"):
        transform(make_raw([{}, {}]), basket)


def test_bad_pack_override_is_an_error(basket):
    with pytest.raises(ValidationError, match="Can't parse pack size"):
        transform(make_raw([{"pack_size": "two litres"}]), basket)


def test_basket_rejects_unknown_category(tmp_path):
    path = tmp_path / "basket.csv"
    path.write_text("product_id,name,brand,category,pack_size\nx,X,B,caviar,100g\n")
    with pytest.raises(ValidationError, match="unknown category 'caviar'"):
        load_basket(path)


def test_write_parquet_is_idempotent(basket, tmp_path):
    out = transform(make_raw([{}, {"product_id": "bananas", "shelf_price": "3.90"}]), basket).data
    target = tmp_path / "processed"
    write_parquet(out, target)
    write_parquet(out, target)  # second run must replace, not append

    files = list(target.glob("year_month=2026-11/*.parquet"))
    assert len(files) == 1
    back = pd.read_parquet(target)
    assert len(back) == 2
    assert set(back["product_id"]) == {"milk-2l", "bananas"}

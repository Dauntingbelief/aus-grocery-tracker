"""Clean and enrich raw price observations.

raw (strings, one row per product per visit)
  -> validated, typed rows
  -> joined to the basket (name, brand, category, default pack size)
  -> derived fields: unit price, regular vs promo price, discount depth, CPI class

Design choices worth knowing:
* Validation collects *every* problem and reports them together, so a typo in row 3
  doesn't hide a typo in row 40.
* Blank shelf_price means "not collected this week" (out of stock, or skipped). Those rows
  are dropped and counted, not treated as errors.
* `regular_price` is the price you'd pay without a promotion. On a promo with a "was"
  price it's the was price; on a promo without one it's unknown (NaN), never guessed.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from grocery_tracker.categories import CATEGORY_TO_CPI, cpi_class_for
from grocery_tracker.schema import PARTITION_KEY, PROCESSED_SCHEMA
from grocery_tracker.sources.base import RAW_COLUMNS
from grocery_tracker.units import parse_pack_size

PROMO_TYPES = {"regular", "special", "price_drop", "multibuy"}

BASKET_COLUMNS = ["product_id", "name", "brand", "category", "pack_size"]

OUTPUT_COLUMNS = [PARTITION_KEY, *PROCESSED_SCHEMA.names]

# One file per partition with a fixed name, so rewriting a month replaces it in place.
PARTITION_FILE = "part-0.parquet"


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"{len(errors)} validation error(s):\n{bullet_list}")


@dataclass
class TransformResult:
    data: pd.DataFrame
    rows_skipped: int  # rows with no shelf price (not collected)


def load_basket(path: str | Path | IO) -> pd.DataFrame:
    """Load and validate the basket definition (the fixed list of tracked products)."""
    basket = pd.read_csv(path, dtype=str, keep_default_na=False).map(str.strip)
    errors: list[str] = []

    missing = [c for c in BASKET_COLUMNS if c not in basket.columns]
    if missing:
        raise ValidationError([f"basket is missing columns: {missing}"])

    dupes = basket.loc[basket["product_id"].duplicated(), "product_id"].tolist()
    if dupes:
        errors.append(f"duplicate product_id in basket: {dupes}")

    for row in basket.itertuples():
        if row.category not in CATEGORY_TO_CPI:
            errors.append(f"basket {row.product_id}: unknown category '{row.category}'")
        try:
            parse_pack_size(row.pack_size)
        except ValueError as exc:
            errors.append(f"basket {row.product_id}: {exc}")

    if errors:
        raise ValidationError(errors)
    return basket[BASKET_COLUMNS]


def _to_number(series: pd.Series) -> pd.Series:
    """'$4.50' / '4.50' / '' -> 4.5 / 4.5 / NaN. Non-numbers become NaN (caught by validation)."""
    cleaned = series.str.replace("$", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned.replace("", np.nan), errors="coerce")


def _validate(df: pd.DataFrame, basket_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for row in df.itertuples():
        where = f"{row.observation_date} {row.store} {row.product_id or '<blank id>'}"
        if row.product_id not in basket_ids:
            errors.append(f"{where}: product_id not in basket")
        if not row.store:
            errors.append(f"{where}: store is blank")
        if row.promo_type not in PROMO_TYPES:
            errors.append(
                f"{where}: promo_type '{row.promo_type}' must be one of {sorted(PROMO_TYPES)}"
            )
        if pd.isna(row.shelf_price_num) or row.shelf_price_num <= 0:
            errors.append(f"{where}: shelf_price '{row.shelf_price}' is not a positive number")
        if row.was_price and pd.isna(row.was_price_num):
            errors.append(f"{where}: was_price '{row.was_price}' is not a number")
        if not pd.isna(row.was_price_num):
            if row.promo_type == "regular":
                errors.append(f"{where}: was_price given but promo_type is 'regular'")
            elif row.was_price_num <= row.shelf_price_num:
                errors.append(
                    f"{where}: was_price {row.was_price_num} must be above "
                    f"shelf_price {row.shelf_price_num}"
                )
        if row.pack_size:
            try:
                parse_pack_size(row.pack_size)
            except ValueError as exc:
                errors.append(f"{where}: {exc}")

    key = ["observation_date", "store", "product_id"]
    for _, dup in df[df.duplicated(key, keep=False)].groupby(key):
        first = dup.iloc[0]
        errors.append(
            f"{first.observation_date} {first.store} {first.product_id}: "
            f"recorded {len(dup)} times on the same day"
        )
    return errors


def transform(raw: pd.DataFrame, basket: pd.DataFrame) -> TransformResult:
    """Turn raw observations into the clean, analysis-ready table."""
    missing = [c for c in RAW_COLUMNS if c not in raw.columns]
    if missing:
        raise ValidationError([f"raw data is missing columns: {missing}"])

    df = raw[RAW_COLUMNS].copy()

    # 1. Drop rows nobody filled in (not collected / out of stock).
    collected = df["shelf_price"] != ""
    rows_skipped = int((~collected).sum())
    df = df[collected].reset_index(drop=True)

    # 2. Normalise and parse.
    df["promo_type"] = df["promo_type"].str.lower().replace("", "regular")
    df["shelf_price_num"] = _to_number(df["shelf_price"])
    df["was_price_num"] = _to_number(df["was_price"])

    # 3. Validate everything at once.
    errors = _validate(df, set(basket["product_id"]))
    if errors:
        raise ValidationError(errors)

    # 4. Join product details from the basket.
    df = df.merge(
        basket.rename(columns={"name": "product_name", "pack_size": "default_pack_size"}),
        on="product_id",
        how="left",
        validate="many_to_one",
    )

    # 5. Pack size: per-observation override wins (lets us spot shrinkflation).
    df["pack_size_changed"] = (df["pack_size"] != "") & (
        df["pack_size"].str.lower().str.replace(" ", "")
        != df["default_pack_size"].str.lower().str.replace(" ", "")
    )
    df["pack_size"] = df["pack_size"].where(df["pack_size"] != "", df["default_pack_size"])
    packs = df["pack_size"].map(parse_pack_size)
    df["pack_quantity"] = packs.map(lambda p: p.quantity)
    df["base_unit"] = packs.map(lambda p: p.base_unit)

    # 6. Prices.
    df["shelf_price"] = df["shelf_price_num"].round(2)
    df["was_price"] = df["was_price_num"].round(2)
    df["is_promo"] = df["promo_type"] != "regular"
    df["regular_price"] = np.where(df["is_promo"], df["was_price"], df["shelf_price"])
    df["discount_pct"] = np.where(
        df["is_promo"], (1 - df["shelf_price"] / df["regular_price"]).round(4), 0.0
    )
    df["unit_price"] = (df["shelf_price"] / df["pack_quantity"]).round(4)
    df["regular_unit_price"] = (df["regular_price"] / df["pack_quantity"]).round(4)

    # 7. CPI mapping.
    cpi = df["category"].map(cpi_class_for)
    df["cpi_class_code"] = cpi.map(lambda c: c.code)
    df["cpi_class_name"] = cpi.map(lambda c: c.name)
    df["cpi_group_code"] = cpi.map(lambda c: c.group_code)
    df["cpi_group_name"] = cpi.map(lambda c: c.group_name)

    # 8. Dates.
    df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
    df["year_month"] = pd.to_datetime(df["observation_date"]).dt.strftime("%Y-%m")

    out = df[OUTPUT_COLUMNS].sort_values(["observation_date", "store", "product_id"])
    return TransformResult(data=out.reset_index(drop=True), rows_skipped=rows_skipped)


def to_parquet_partitions(df: pd.DataFrame) -> dict[str, bytes]:
    """Split by month and serialise each month to Parquet bytes.

    Returns {"year_month=2026-11/part-0.parquet": b"..."}. Keys are relative paths, so the same
    output can go to a local folder or an S3 prefix. The partition column lives in the folder
    name (Hive convention), not inside the file, and the schema is fixed by PROCESSED_SCHEMA.
    """
    files: dict[str, bytes] = {}
    for month, part in df.groupby(PARTITION_KEY, sort=True):
        table = pa.Table.from_pandas(
            part[PROCESSED_SCHEMA.names], schema=PROCESSED_SCHEMA, preserve_index=False
        )
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")
        files[f"{PARTITION_KEY}={month}/{PARTITION_FILE}"] = buf.getvalue()
    return files


def write_parquet(df: pd.DataFrame, out_dir: str | Path) -> list[Path]:
    """Write month partitions to a local folder (data/processed/prices/year_month=.../).

    Each run overwrites the same file name per month, so re-running the transform is
    idempotent: no duplicate rows, however many times you run it.
    """
    written = []
    for rel_path, payload in to_parquet_partitions(df).items():
        target = Path(out_dir) / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        written.append(target)
    return written

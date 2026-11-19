"""Single source of truth for the processed table's schema.

The Parquet writer and the Glue table definition (infra/) both read from this, so the files
in S3 and the table Athena queries can't drift apart.
"""

from __future__ import annotations

import pyarrow as pa

PARTITION_KEY = "year_month"  # Hive partition folder: processed/prices/year_month=2026-11/

PROCESSED_SCHEMA = pa.schema(
    [
        ("observation_date", pa.date32()),
        ("store", pa.string()),
        ("product_id", pa.string()),
        ("product_name", pa.string()),
        ("brand", pa.string()),
        ("category", pa.string()),
        ("cpi_class_code", pa.string()),
        ("cpi_class_name", pa.string()),
        ("cpi_group_code", pa.string()),
        ("cpi_group_name", pa.string()),
        ("pack_size", pa.string()),
        ("pack_quantity", pa.float64()),
        ("base_unit", pa.string()),
        ("pack_size_changed", pa.bool_()),
        ("shelf_price", pa.float64()),
        ("was_price", pa.float64()),
        ("promo_type", pa.string()),
        ("is_promo", pa.bool_()),
        ("regular_price", pa.float64()),
        ("discount_pct", pa.float64()),
        ("unit_price", pa.float64()),
        ("regular_unit_price", pa.float64()),
        ("notes", pa.string()),
        ("source", pa.string()),
    ]
)

_GLUE_TYPES = {
    pa.string(): "string",
    pa.float64(): "double",
    pa.bool_(): "boolean",
    pa.date32(): "date",
}


def glue_columns(schema: pa.Schema = PROCESSED_SCHEMA) -> list[dict[str, str]]:
    """Schema as Glue/Athena column definitions: [{'name': ..., 'type': ...}, ...]."""
    return [{"name": f.name, "type": _GLUE_TYPES[f.type]} for f in schema]

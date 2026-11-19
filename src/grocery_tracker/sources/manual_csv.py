"""Price source: hand-recorded weekly CSV files.

Layout mirrors the S3 raw zone (Hive-style partitions), so the same files can be
uploaded to s3://<bucket>/raw/prices/date=YYYY-MM-DD/prices.csv unchanged:

    data/raw/prices/date=2026-11-22/prices.csv

The observation date comes from the folder name, so there's one less column to type.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path, PurePath
from typing import IO

import pandas as pd

from grocery_tracker.sources.base import RAW_COLUMNS

_DATE_DIR_RE = re.compile(r"^date=(\d{4}-\d{2}-\d{2})$")

# Columns the person fills in. Extra helper columns (e.g. "name") are ignored.
REQUIRED_CSV_COLUMNS = ["store", "product_id", "shelf_price", "promo_type", "was_price"]
OPTIONAL_CSV_COLUMNS = ["pack_size", "notes"]


def partition_date(path: PurePath) -> date:
    """Read the observation date from a 'date=YYYY-MM-DD' parent folder."""
    match = _DATE_DIR_RE.match(path.parent.name)
    if not match:
        raise ValueError(f"{path}: parent folder must be named 'date=YYYY-MM-DD'.")
    return date.fromisoformat(match.group(1))


def read_observation_csv(
    file: str | Path | IO[str], observation_date: date, source: str = "manual_csv"
) -> pd.DataFrame:
    """Read one weekly CSV into the canonical raw schema (all strings)."""
    df = pd.read_csv(file, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]

    missing = [c for c in REQUIRED_CSV_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    for col in OPTIONAL_CSV_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df["observation_date"] = observation_date.isoformat()
    df["source"] = source
    return df[RAW_COLUMNS].map(str.strip)


class ManualCsvSource:
    name = "manual_csv"

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def files(self) -> list[Path]:
        return sorted(self.root.glob("date=*/*.csv"))

    def read(self) -> pd.DataFrame:
        frames = [read_observation_csv(f, partition_date(f), self.name) for f in self.files()]
        if not frames:
            return pd.DataFrame(columns=RAW_COLUMNS, dtype=str)
        return pd.concat(frames, ignore_index=True)

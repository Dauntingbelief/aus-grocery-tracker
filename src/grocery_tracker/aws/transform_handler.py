"""AWS Lambda entry point: rebuild processed Parquet whenever a raw CSV lands in S3.

Trigger: S3 ObjectCreated on raw/prices/*.csv
Flow:    read basket + every raw CSV -> transform() -> overwrite processed/prices/ partitions

Why reprocess *everything* each time instead of just the new file? The dataset is tiny
(~60 rows/week), so a full rebuild takes about a second, and it keeps the job idempotent:
a corrected CSV, a re-upload, or a duplicate S3 event all give the same result.

pandas and pyarrow come from the AWS SDK for pandas managed Lambda layer; boto3 is built
into the Lambda runtime. This module has no other dependencies.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import PurePosixPath
from typing import Any

import pandas as pd

from grocery_tracker.sources.base import RAW_COLUMNS
from grocery_tracker.sources.manual_csv import partition_date, read_observation_csv
from grocery_tracker.transform import load_basket, to_parquet_partitions, transform

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys, token = [], None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        keys += [obj["Key"] for obj in page.get("Contents", [])]
        if not page.get("IsTruncated"):
            return sorted(keys)
        token = page["NextContinuationToken"]


def _read_text(s3, bucket: str, key: str) -> str:
    return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")


def read_raw_from_s3(s3, bucket: str, raw_prefix: str) -> pd.DataFrame:
    """Read every raw/prices/date=YYYY-MM-DD/*.csv object into the canonical raw schema."""
    frames = []
    for key in _list_keys(s3, bucket, raw_prefix):
        if not key.endswith(".csv"):
            continue
        # partition_date() works on S3 keys too: it only looks at the parent "folder" name.
        observed = partition_date(PurePosixPath(key))
        frames.append(read_observation_csv(io.StringIO(_read_text(s3, bucket, key)), observed))
    if not frames:
        return pd.DataFrame(columns=RAW_COLUMNS, dtype=str)
    return pd.concat(frames, ignore_index=True)


def write_processed_to_s3(s3, bucket: str, processed_prefix: str, df: pd.DataFrame) -> list[str]:
    """Overwrite each month's partition file. Fixed file names make this idempotent."""
    written = []
    for rel_path, payload in to_parquet_partitions(df).items():
        key = f"{processed_prefix}{rel_path}"
        s3.put_object(Bucket=bucket, Key=key, Body=payload)
        written.append(key)
    return written


def run(s3, bucket: str, raw_prefix: str, processed_prefix: str, basket_key: str) -> dict:
    basket = load_basket(io.StringIO(_read_text(s3, bucket, basket_key)))
    raw = read_raw_from_s3(s3, bucket, raw_prefix)
    if raw.empty:
        return {"status": "no_data", "observations": 0}

    result = transform(raw, basket)  # raises ValidationError -> visible in CloudWatch Logs
    written = write_processed_to_s3(s3, bucket, processed_prefix, result.data)
    return {
        "status": "ok",
        "observations": len(result.data),
        "rows_skipped": result.rows_skipped,
        "files_written": written,
    }


def handler(event: dict[str, Any], context: Any) -> dict:
    import boto3  # imported here so unit tests don't need boto3 installed

    triggered_by = [r["s3"]["object"]["key"] for r in event.get("Records", [])]
    logger.info("Triggered by: %s", triggered_by)
    summary = run(
        s3=boto3.client("s3"),
        bucket=os.environ["DATA_BUCKET"],
        raw_prefix=os.environ.get("RAW_PREFIX", "raw/prices/"),
        processed_prefix=os.environ.get("PROCESSED_PREFIX", "processed/prices/"),
        basket_key=os.environ.get("BASKET_KEY", "reference/basket.csv"),
    )
    logger.info(json.dumps(summary))
    return summary

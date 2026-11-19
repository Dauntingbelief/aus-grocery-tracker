"""Tests for the Lambda handler logic, using an in-memory stand-in for the S3 client."""

import io

import pandas as pd
import pytest
from conftest import BASKET_CSV

from grocery_tracker.aws.transform_handler import run
from grocery_tracker.transform import ValidationError

BUCKET = "test-bucket"


class FakeS3:
    """Implements just the four S3 client calls the handler uses."""

    def __init__(self, page_size: int = 1000):
        self.objects: dict[str, bytes] = {}
        self.page_size = page_size

    def put_object(self, Bucket, Key, Body):  # noqa: N803 (boto3 argument names)
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + self.page_size]
        more = start + self.page_size < len(keys)
        resp = {"Contents": [{"Key": k} for k in page], "IsTruncated": more}
        if more:
            resp["NextContinuationToken"] = str(start + self.page_size)
        return resp


def week_csv(price: str) -> str:
    return (
        "product_id,store,shelf_price,promo_type,was_price\n"
        f"milk-2l,store-01,{price},,\n"
        "bananas,store-01,,,\n"
    )


def run_handler(s3):
    return run(s3, BUCKET, "raw/prices/", "processed/prices/", "reference/basket.csv")


@pytest.fixture
def s3():
    fake = FakeS3(page_size=1)  # page_size=1 forces the pagination loop to run
    fake.put_object(BUCKET, "reference/basket.csv", BASKET_CSV)
    return fake


def read_partition(s3, key):
    return pd.read_parquet(io.BytesIO(s3.objects[key]))


def test_run_writes_month_partitions(s3):
    s3.put_object(BUCKET, "raw/prices/date=2026-11-22/prices.csv", week_csv("3.10"))
    s3.put_object(BUCKET, "raw/prices/date=2026-12-06/prices.csv", week_csv("3.20"))

    summary = run_handler(s3)

    assert summary["status"] == "ok"
    assert summary["observations"] == 2
    assert summary["rows_skipped"] == 2
    assert summary["files_written"] == [
        "processed/prices/year_month=2026-11/part-0.parquet",
        "processed/prices/year_month=2026-12/part-0.parquet",
    ]
    nov = read_partition(s3, "processed/prices/year_month=2026-11/part-0.parquet")
    assert nov["unit_price"].tolist() == [1.55]
    assert "year_month" not in nov.columns  # lives in the folder name, not the file


def test_rerun_is_idempotent(s3):
    s3.put_object(BUCKET, "raw/prices/date=2026-11-22/prices.csv", week_csv("3.10"))
    run_handler(s3)
    before = dict(s3.objects)
    run_handler(s3)
    assert s3.objects.keys() == before.keys()


def test_corrected_csv_replaces_old_values(s3):
    key = "raw/prices/date=2026-11-22/prices.csv"
    s3.put_object(BUCKET, key, week_csv("3.10"))
    run_handler(s3)
    s3.put_object(BUCKET, key, week_csv("3.30"))  # fixed a typo and re-uploaded
    run_handler(s3)
    nov = read_partition(s3, "processed/prices/year_month=2026-11/part-0.parquet")
    assert nov["shelf_price"].tolist() == [3.30]


def test_non_csv_objects_are_ignored(s3):
    s3.put_object(BUCKET, "raw/prices/.DS_Store", "junk")
    assert run_handler(s3) == {"status": "no_data", "observations": 0}


def test_invalid_data_raises_and_writes_nothing(s3):
    s3.put_object(BUCKET, "raw/prices/date=2026-11-22/prices.csv", week_csv("abc"))
    with pytest.raises(ValidationError):
        run_handler(s3)
    assert not any(k.startswith("processed/") for k in s3.objects)

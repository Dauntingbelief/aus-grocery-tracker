from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from grocery_tracker.categories import CATEGORY_TO_CPI
from grocery_tracker.cli import main
from grocery_tracker.sources import RAW_COLUMNS, ManualCsvSource
from grocery_tracker.sources.manual_csv import partition_date
from grocery_tracker.transform import load_basket

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_real_basket_is_valid():
    """Guards the committed basket: unique ids, known categories, parseable pack sizes."""
    basket = load_basket(REPO_ROOT / "data" / "basket.csv")
    assert 50 <= len(basket) <= 100
    assert set(basket["category"]) <= set(CATEGORY_TO_CPI)


def test_partition_date_from_folder():
    assert partition_date(Path("raw/prices/date=2026-11-22/prices.csv")) == date(2026, 11, 22)
    with pytest.raises(ValueError):
        partition_date(Path("raw/prices/2026-11-22/prices.csv"))


def test_manual_csv_source_reads_partitions(tmp_path):
    for d in ["2026-11-15", "2026-11-22"]:
        folder = tmp_path / f"date={d}"
        folder.mkdir()
        (folder / "prices.csv").write_text(
            "product_id,name,store,shelf_price,promo_type,was_price\n"
            "milk-2l,Milk, store-01 ,3.10,,\n"
        )
    df = ManualCsvSource(tmp_path).read()
    assert list(df.columns) == RAW_COLUMNS
    assert list(df["observation_date"]) == ["2026-11-15", "2026-11-22"]
    assert df["store"].iloc[0] == "store-01"  # whitespace stripped
    assert (df["pack_size"] == "").all()  # optional column filled in


def test_manual_csv_source_empty_dir(tmp_path):
    assert ManualCsvSource(tmp_path).read().empty


def test_cli_end_to_end(tmp_path, basket_path, capsys):
    data_dir = basket_path.parent
    assert main(["--data-dir", str(data_dir), "new-week", "--date", "2026-11-22"]) == 0
    csv = data_dir / "raw" / "prices" / "date=2026-11-22" / "prices.csv"

    # Refuses to overwrite a week you've started filling in
    assert main(["--data-dir", str(data_dir), "new-week", "--date", "2026-11-22"]) == 1

    week = pd.read_csv(csv, dtype=str, keep_default_na=False)
    week.loc[week["product_id"] == "milk-2l", "shelf_price"] = "3.10"
    week.to_csv(csv, index=False)

    assert main(["--data-dir", str(data_dir), "transform"]) == 0
    assert "1 observations" in capsys.readouterr().out
    out = pd.read_parquet(data_dir / "processed" / "prices")
    assert out["unit_price"].tolist() == [1.55]


def test_cli_reports_validation_errors(tmp_path, basket_path, capsys):
    data_dir = basket_path.parent
    main(["--data-dir", str(data_dir), "new-week", "--date", "2026-11-22"])
    csv = data_dir / "raw" / "prices" / "date=2026-11-22" / "prices.csv"
    week = pd.read_csv(csv, dtype=str, keep_default_na=False)
    week.loc[0, "shelf_price"] = "abc"
    week.to_csv(csv, index=False)

    assert main(["--data-dir", str(data_dir), "validate"]) == 1
    assert "not a positive number" in capsys.readouterr().err

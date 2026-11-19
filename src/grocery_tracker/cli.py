"""Command-line entry point: `grocery-tracker <command>`.

grocery-tracker new-week --date 2026-11-22   # make this week's blank CSV to fill in
grocery-tracker validate                     # check all raw CSVs, change nothing
grocery-tracker transform                    # raw CSVs -> data/processed/prices/*.parquet
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from grocery_tracker.sources import ManualCsvSource
from grocery_tracker.transform import ValidationError, load_basket, transform, write_parquet

TEMPLATE_COLUMNS = [
    "product_id",
    "name",
    "default_pack_size",
    "store",
    "shelf_price",
    "promo_type",
    "was_price",
    "pack_size",
    "notes",
]


def _paths(data_dir: Path) -> dict[str, Path]:
    return {
        "basket": data_dir / "basket.csv",
        "raw": data_dir / "raw" / "prices",
        "processed": data_dir / "processed" / "prices",
    }


def cmd_new_week(args: argparse.Namespace) -> int:
    paths = _paths(args.data_dir)
    basket = load_basket(paths["basket"])
    target = paths["raw"] / f"date={args.date.isoformat()}" / "prices.csv"
    if target.exists():
        print(f"{target} already exists; not overwriting.", file=sys.stderr)
        return 1

    template = pd.DataFrame(
        {
            "product_id": basket["product_id"],
            "name": basket["name"],
            "default_pack_size": basket["pack_size"],
            "store": args.store,
        }
    ).reindex(columns=TEMPLATE_COLUMNS, fill_value="")
    target.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(target, index=False)
    print(f"Created {target} with {len(template)} products. Fill in shelf_price (and promo info).")
    return 0


def _run(args: argparse.Namespace, write: bool) -> int:
    paths = _paths(args.data_dir)
    source = ManualCsvSource(paths["raw"])
    raw = source.read()
    if raw.empty:
        print(f"No CSV files found under {paths['raw']}. Try `grocery-tracker new-week`.")
        return 1
    try:
        result = transform(raw, load_basket(paths["basket"]))
    except ValidationError as exc:
        print(exc, file=sys.stderr)
        return 1

    df = result.data
    print(
        f"OK: {len(df)} observations from {len(source.files())} file(s), "
        f"{df['observation_date'].nunique()} date(s), {df['product_id'].nunique()} products; "
        f"{result.rows_skipped} blank row(s) skipped; {int(df['is_promo'].sum())} on promotion."
    )
    if write:
        write_parquet(df, paths["processed"])
        print(f"Wrote Parquet to {paths['processed']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="grocery-tracker", description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-week", help="create a blank CSV for one collection date")
    p_new.add_argument("--date", type=date.fromisoformat, default=date.today())
    p_new.add_argument("--store", default="store-01", help="anonymised store label")
    p_new.set_defaults(func=cmd_new_week)

    p_val = sub.add_parser("validate", help="check raw CSVs without writing anything")
    p_val.set_defaults(func=lambda a: _run(a, write=False))

    p_tr = sub.add_parser("transform", help="validate raw CSVs and write processed Parquet")
    p_tr.set_defaults(func=lambda a: _run(a, write=True))

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

# Aussie Grocery Basket Tracker

[![CI](https://github.com/Dauntingbelief/aus-grocery-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/Dauntingbelief/aus-grocery-tracker/actions/workflows/ci.yml)

Tracks a fixed basket of ~60 Australian supermarket products week by week, and compares
category price changes with ABS CPI food sub-indexes. It also measures how often items go on
special and how deep the discounts really are.

> 🚧 Work in progress. Full story, architecture diagram, dashboard and findings coming soon.

## Quickstart

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
grocery-tracker new-week --date 2026-11-22
```

## Repo layout

```
src/grocery_tracker/   pipeline code (sources/, units, transform, categories, cli)
data/basket.csv        the fixed basket of tracked products
data/raw/prices/       hand-recorded weekly CSVs (date=YYYY-MM-DD/prices.csv)
tests/                 pytest suite
docs/                  data-sourcing decision, collection guide
infra/                 AWS CDK app (coming)
notebooks/             analysis (coming)
```

See [docs/data-sourcing.md](docs/data-sourcing.md) for why prices are hand-collected rather
than scraped.

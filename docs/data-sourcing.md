# Data sourcing decision

*Researched 18 Nov 2026. Not legal advice. These are my notes on why the project collects data the way it does.*

## Summary

| Source | Automated collection? | Why |
|---|---|---|
| Coles website | No | Website terms (cl. 2) limit use to personal purposes without written consent, and ban copying or republishing content and putting heavy load on the site. Pricing data is excluded from Coles' IP claim (cl. 4), but republishing it in a public dashboard still isn't personal use. |
| Woolworths website | No | robots.txt and the terms both return HTTP 403 to automated clients. The site actively refuses bots. |
| ALDI website | No | The website terms say users must not access the site "through any automated means"; only search engines are exempt. |
| Public retailer APIs | n/a | None exist. |
| Third-party trackers (Hot Prices AU, auscost) | No | They scrape the retailers and publish no bulk download or data licence. |
| Kaggle / academic datasets | Not suitable | One-off snapshots (e.g. Macquarie, Dec 2020), not time series. |
| **ABS Data API (CPI)** | **Yes** | Public SDMX API, no key needed. ABS content is generally CC BY 4.0 (attribute the ABS). |

## Decision

1. **Basket prices: hand-recorded weekly CSV.** About 60 products at one store. I record only what any customer can see on the shelf or on the public website in a normal browser. I don't use internal retailer systems or employee-only information.
2. **CPI: automated** from the ABS Data API, dataflow `ABS,CPI,2.0.0` (monthly, Sep 2025 = 100).
3. **Swappable source.** The pipeline reads prices through a `PriceSource` interface (`src/grocery_tracker/sources/`). If a licensed feed or written permission becomes available, adding a new source class is the only change needed.

## ABS CPI details (verified against the live API)

- Key order: `MEASURE.INDEX.TSEST.REGION.FREQ`
- `MEASURE=1` index numbers · `TSEST=10` original / `20` seasonally adjusted · `REGION=50` Australia · `FREQ=M`
- Example (food group, all adjustments): `https://data.api.abs.gov.au/rest/data/ABS,CPI,2.0.0/1.20001..50.M?startPeriod=2025-01&format=csvfilewithlabels`
- Expenditure-class codes used by the basket are in `src/grocery_tracker/categories.py`.
- Gotchas: an unfiltered `all` query exceeds the API's 10 MB response limit. The dataflow is annotated `NonProductionDataflow`, so we pin the version and test the response schema.

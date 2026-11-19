# Weekly price collection

Same store, same day of the week, every week. Consistency matters more than volume.

```bash
grocery-tracker new-week --date 2026-11-22 --store store-01
# fill in data/raw/prices/date=2026-11-22/prices.csv
grocery-tracker validate
grocery-tracker transform
```

## Columns to fill in

| Column | What to write |
|---|---|
| `shelf_price` | Price you'd pay today, e.g. `4.50`. **Leave blank** if out of stock or not checked; the row is skipped. |
| `promo_type` | Blank/`regular`, `special` (ticket with a "was" price), `price_drop` (long-term price cut), `multibuy` (e.g. 2 for $7) |
| `was_price` | The "was" price printed on a promo ticket. Leave blank if there isn't one. |
| `pack_size` | Only if the pack differs from `default_pack_size` (e.g. `450g` instead of `500g`), which flags shrinkflation |
| `notes` | Anything odd |

- **Per-kg items** (loose fruit and veg, meat by weight): write the price per kg in `shelf_price`.
- **Multibuy:** write the per-item price when you take the deal (2 for $7 → `3.50`), and the single-item price as `was_price`.
- **Store label:** use an anonymous label like `store-01`, not the suburb. The repo is public.
- Record only customer-visible information. Don't use internal systems or employee-only knowledge.

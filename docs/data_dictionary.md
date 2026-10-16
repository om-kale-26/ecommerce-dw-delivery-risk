# Data Dictionary

Source: [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(~100k orders, Sep 2016 - Oct 2018, real anonymized marketplace data).

## Important source quirk

`customer_id` in Olist's raw data is minted **per order**, not per person.
The real, repeating person is `customer_unique_id`. This warehouse treats
`customer_unique_id` as the SCD2 business key for `dim_customer`, and
resolves every fact's `customer_key` through that mapping. Calling this out
explicitly is one of the better "I understand the data, not just the SQL"
signals for a portfolio project.

## Dimensions

| Table | Grain | Notes |
|---|---|---|
| `dim_date` | one row per calendar day, 2016-2018 | pre-populated |
| `dim_customer` | one row per **version** of a person (SCD2) | keyed on `customer_unique_id`; new version when city/state changes across orders |
| `dim_product` | one row per product | joined to `dim_category` for the English category name |
| `dim_category` | one row per product category | Portuguese + English names (Olist ships a translation file) |
| `dim_seller` | one row per seller | Olist is a marketplace — sellers are independent of Olist itself |

## Facts

| Table | Grain | Replaces / notes |
|---|---|---|
| `fact_orders` | one row per order | order-lifecycle timestamps + delivery delay/lateness flags. **This is the stand-in for "returns" — Olist has no returns dataset, but it has rich delivery-performance and cancellation data, which is arguably more useful.** |
| `fact_order_items` | one row per order line (product × seller within an order) | the main revenue fact |
| `fact_payments` | one row per payment attempt/installment line | an order can have multiple payment rows (e.g., split across a voucher + credit card) |
| `fact_reviews` | one row per review | one review per order in practice |

## Known simplifications (documented on purpose, not hidden)

- `customer_key` on facts resolves to the customer's **current** SCD2 version at load
  time, not the version that was current on the order date. Fixing this is a clean
  v2 upgrade (join on `effective_from <= order_date < effective_to`).
- `dim_customer` SCD2 versioning is a full rebuild each run, not incremental.
- Geolocation data (`olist_geolocation_dataset.csv`) is not modeled into the star
  schema — it's zip-prefix-grain with many lat/lng pairs per prefix, which is a
  different grain problem. Left as a clearly-labeled v2 extension.

"""
load_dimensions.py - Staging -> Warehouse (dimensions).

dim_date:      generated once, deterministically, for a fixed date range
               that actually covers the Olist dataset (2016-2018).
dim_category / dim_product / dim_seller: full-refresh with surrogate keys.
dim_customer:  SLOWLY CHANGING DIMENSION TYPE 2, keyed on customer_unique_id.

    Why this is the interesting bit: Olist mints a brand-new customer_id for
    every order (it is really an "order-customer" key, not a person key).
    customer_unique_id is the real, repeating person. So a naive load would
    treat every order as a "new customer". Instead we:
      1. join staging.customers to staging.orders to get each customer_id's
         purchase timestamp,
      2. group by customer_unique_id and walk each person's orders in time
         order,
      3. open a new SCD2 version only when city/state actually changes
         between consecutive orders for the same person.

Run:
    python load_dimensions.py --all
"""
import argparse
import sys
from datetime import date, datetime, timedelta

import pandas as pd

sys.path.append("../ingestion")
import config
import clickhouse_connect


def get_client():
    return clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
    )


def load_dim_date(client, start_year=2016, end_year=2018):
    rows = []
    d = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    while d <= end:
        rows.append([
            int(d.strftime("%Y%m%d")), d, d.day, d.month, d.strftime("%B"),
            (d.month - 1) // 3 + 1, d.year, d.strftime("%A"),
            1 if d.weekday() >= 5 else 0,
        ])
        d += timedelta(days=1)
    client.command("TRUNCATE TABLE IF EXISTS warehouse.dim_date")
    client.insert(
        "warehouse.dim_date", rows,
        column_names=["date_key", "date", "day", "month", "month_name", "quarter", "year", "weekday", "is_weekend"],
    )
    print(f"warehouse.dim_date: {len(rows)} rows ({start_year}-{end_year})")


def load_dim_category(client):
    df = client.query_df("SELECT * FROM staging.category_translation")
    df = df.reset_index(drop=True)
    df.insert(0, "category_key", range(1, len(df) + 1))
    client.command("TRUNCATE TABLE IF EXISTS warehouse.dim_category")
    client.insert_df(
        "warehouse.dim_category",
        df.rename(columns={
            "product_category_name": "category_name_pt",
            "product_category_name_english": "category_name_english",
        })[["category_key", "category_name_pt", "category_name_english"]],
    )
    print(f"warehouse.dim_category: {len(df)} rows")
    # Some products reference a category_name that has no translation row -
    # add an "unknown" catch-all so dim_product joins never drop rows.
    max_key = df["category_key"].max() if len(df) else 0
    client.insert(
        "warehouse.dim_category",
        [[int(max_key) + 1, "unknown", "unknown"]],
        column_names=["category_key", "category_name_pt", "category_name_english"],
    )


def load_dim_product(client):
    products = client.query_df("SELECT * FROM staging.products")
    categories = client.query_df("SELECT category_key, category_name_pt FROM warehouse.dim_category")
    merged = products.merge(
        categories, left_on="product_category_name", right_on="category_name_pt", how="left"
    )
    unknown_key = categories.loc[categories["category_name_pt"] == "unknown", "category_key"].iloc[0]
    merged["category_key"] = merged["category_key"].fillna(unknown_key).astype(int)
    merged = merged.reset_index(drop=True)
    merged.insert(0, "product_key", range(1, len(merged) + 1))
    client.command("TRUNCATE TABLE IF EXISTS warehouse.dim_product")
    client.insert_df(
        "warehouse.dim_product",
        merged[["product_key", "product_id", "category_key", "product_photos_qty",
                "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]]
        .rename(columns={"product_photos_qty": "photos_qty", "product_weight_g": "weight_g",
                          "product_length_cm": "length_cm", "product_height_cm": "height_cm",
                          "product_width_cm": "width_cm"}),
    )
    print(f"warehouse.dim_product: {len(merged)} rows")


def load_dim_seller(client):
    df = client.query_df("SELECT * FROM staging.sellers")
    df = df.reset_index(drop=True)
    df.insert(0, "seller_key", range(1, len(df) + 1))
    client.command("TRUNCATE TABLE IF EXISTS warehouse.dim_seller")
    client.insert_df(
        "warehouse.dim_seller",
        df.rename(columns={"seller_city": "city", "seller_state": "state",
                            "seller_zip_code_prefix": "zip_code_prefix"})
        [["seller_key", "seller_id", "city", "state", "zip_code_prefix"]],
    )
    print(f"warehouse.dim_seller: {len(df)} rows")


def load_dim_customer_scd2(client):
    """
    Full rebuild, keyed on customer_unique_id. For each person, orders their
    per-order customer_id rows by first purchase timestamp and opens a new
    SCD2 version whenever city/state changes between consecutive orders.

    This is a full-refresh implementation (simplest correct version for a
    portfolio project) - see README's roadmap for an incremental version.
    """
    customers = client.query_df(
        "SELECT customer_id, customer_unique_id, customer_city, customer_state, "
        "customer_zip_code_prefix FROM staging.customers"
    )
    orders = client.query_df("SELECT customer_id, order_purchase_timestamp FROM staging.orders")
    merged = customers.merge(orders, on="customer_id", how="left")
    # a person with no matching order yet still gets a dim row; sort NaT last
    merged["order_purchase_timestamp"] = pd.to_datetime(merged["order_purchase_timestamp"])
    merged = merged.sort_values(["customer_unique_id", "order_purchase_timestamp"], na_position="last")

    rows = []
    key = 1
    for unique_id, grp in merged.groupby("customer_unique_id", sort=False):
        prev_city, prev_state = None, None
        effective_from = None
        for i, (_, r) in enumerate(grp.iterrows()):
            ts = r["order_purchase_timestamp"]
            effective_from = ts if pd.notna(ts) else datetime(2016, 1, 1)
            city, state = r["customer_city"], r["customer_state"]
            if i == 0 or city != prev_city or state != prev_state:
                # close previous version, if any
                # row layout: [key, unique_id, city, state, zip, effective_from, effective_to, is_current]
                if rows and rows[-1][1] == unique_id and rows[-1][6] is None:
                    rows[-1][6] = effective_from  # effective_to
                    rows[-1][7] = 0               # is_current
                rows.append([key, unique_id, city, state, r["customer_zip_code_prefix"],
                             effective_from, None, 1])
                key += 1
            prev_city, prev_state = city, state

    client.command("TRUNCATE TABLE IF EXISTS warehouse.dim_customer")
    client.insert(
        "warehouse.dim_customer", rows,
        column_names=["customer_key", "customer_unique_id", "city", "state", "zip_code_prefix",
                      "effective_from", "effective_to", "is_current"],
    )
    n_people = merged["customer_unique_id"].nunique()
    print(f"warehouse.dim_customer (SCD2): {len(rows)} versions for {n_people} unique people")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    client = get_client()

    if args.all:
        load_dim_date(client)
        load_dim_category(client)
        load_dim_product(client)
        load_dim_seller(client)
        load_dim_customer_scd2(client)


if __name__ == "__main__":
    main()

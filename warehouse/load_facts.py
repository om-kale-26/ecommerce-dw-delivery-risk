"""
load_facts.py - Staging -> Warehouse (facts).

Joins cleaned staging data to dimension business keys to resolve surrogate
keys. Rows that can't resolve a required dimension key are quarantined
(written to raw.rejected_rows) instead of silently dropped or loaded with
a broken key.

Every fact resolves customer_key the same way: staging.customers maps
order-level customer_id -> customer_unique_id, then that's joined to the
CURRENT SCD2 version of the person in warehouse.dim_customer. Resolving
against the version that was current on the order date (not load date) is
called out in docs/architecture.md as a v2 improvement.

Run:
    python load_facts.py --all
"""
import argparse
import json
import sys
import uuid

import clickhouse_connect
import pandas as pd

sys.path.append("../ingestion")
import config


def get_client():
    return clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
    )


def write_rejected(client, table_name, run_id, rows, reason):
    if len(rows) == 0:
        return
    payload = [[run_id, table_name, json.dumps(r, default=str), reason] for r in rows]
    client.insert("raw.rejected_rows", payload,
                  column_names=["run_id", "source_table", "raw_row_json", "rejection_reason"])


def _customer_key_map(client):
    """order-level customer_id -> current customer_key, via customer_unique_id."""
    cust = client.query_df("SELECT customer_id, customer_unique_id FROM staging.customers")
    dim = client.query_df(
        "SELECT customer_unique_id, customer_key FROM warehouse.dim_customer WHERE is_current = 1"
    )
    return cust.merge(dim, on="customer_unique_id", how="left")[["customer_id", "customer_key"]]


def load_fact_orders(client):
    run_id = str(uuid.uuid4())
    orders = client.query_df("SELECT * FROM staging.orders")
    cust_map = _customer_key_map(client)

    before = len(orders)
    df = orders.merge(cust_map, on="customer_id", how="left")

    unresolved = df[df["customer_key"].isna()]
    if len(unresolved):
        write_rejected(client, "fact_orders", run_id, unresolved.to_dict("records"), "unresolved_customer_key")
    resolved = df.dropna(subset=["customer_key"]).copy()
    resolved["customer_key"] = resolved["customer_key"].astype(int)

    resolved["date_key_purchase"] = pd.to_datetime(resolved["order_purchase_timestamp"]).dt.strftime("%Y%m%d").astype(int)

    delivered = pd.to_datetime(resolved["order_delivered_customer_date"])
    purchase = pd.to_datetime(resolved["order_purchase_timestamp"])
    estimate = pd.to_datetime(resolved["order_estimated_delivery_date"])

    resolved["delivery_days"] = (delivered - purchase).dt.days
    resolved["delay_vs_estimate_days"] = (delivered - estimate).dt.days
    resolved["is_late"] = (resolved["delay_vs_estimate_days"] > 0).fillna(False).astype(int)
    resolved["is_delivered"] = (resolved["order_status"] == "delivered").astype(int)
    resolved["is_canceled"] = (resolved["order_status"] == "canceled").astype(int)

    out_cols = ["order_id", "date_key_purchase", "customer_key", "order_status",
                "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
                "order_delivered_customer_date", "order_estimated_delivery_date",
                "delivery_days", "delay_vs_estimate_days", "is_late", "is_delivered", "is_canceled"]
    rename = {
        "order_purchase_timestamp": "purchase_ts", "order_approved_at": "approved_at",
        "order_delivered_carrier_date": "delivered_carrier_at",
        "order_delivered_customer_date": "delivered_customer_at",
        "order_estimated_delivery_date": "estimated_delivery_at",
    }
    client.command("TRUNCATE TABLE IF EXISTS warehouse.fact_orders")
    client.insert_df("warehouse.fact_orders", resolved[out_cols].rename(columns=rename))
    print(f"warehouse.fact_orders: loaded={len(resolved)} rejected={before - len(resolved)}")


def load_fact_order_items(client):
    run_id = str(uuid.uuid4())
    items = client.query_df("SELECT * FROM staging.order_items")
    orders = client.query_df("SELECT order_id, customer_id, order_purchase_timestamp FROM staging.orders")
    cust_map = _customer_key_map(client)
    products = client.query_df("SELECT product_id, product_key FROM warehouse.dim_product")
    sellers = client.query_df("SELECT seller_id, seller_key FROM warehouse.dim_seller")

    df = items.merge(orders, on="order_id", how="left")
    before = len(df)
    df = df.merge(cust_map, on="customer_id", how="left")
    df = df.merge(products, on="product_id", how="left")
    df = df.merge(sellers, on="seller_id", how="left")

    key_cols = ["customer_key", "product_key", "seller_key"]
    unresolved = df[df[key_cols].isna().any(axis=1)]
    if len(unresolved):
        write_rejected(client, "fact_order_items", run_id, unresolved.to_dict("records"), "unresolved_dimension_key")
    resolved = df.dropna(subset=key_cols).copy()
    for c in key_cols:
        resolved[c] = resolved[c].astype(int)

    resolved["date_key"] = pd.to_datetime(resolved["order_purchase_timestamp"]).dt.strftime("%Y%m%d").astype(int)
    resolved["total_amount"] = resolved["price"] + resolved["freight_value"]

    out_cols = ["order_id", "order_item_id", "date_key", "customer_key", "product_key",
                "seller_key", "price", "freight_value", "total_amount"]
    client.command("TRUNCATE TABLE IF EXISTS warehouse.fact_order_items")
    client.insert_df("warehouse.fact_order_items", resolved[out_cols])
    print(f"warehouse.fact_order_items: loaded={len(resolved)} rejected={before - len(resolved)}")


def load_fact_payments(client):
    run_id = str(uuid.uuid4())
    payments = client.query_df("SELECT * FROM staging.payments")
    orders = client.query_df("SELECT order_id, customer_id, order_purchase_timestamp FROM staging.orders")
    cust_map = _customer_key_map(client)

    df = payments.merge(orders, on="order_id", how="left")
    before = len(df)
    df = df.merge(cust_map, on="customer_id", how="left")

    unresolved = df[df["customer_key"].isna()]
    if len(unresolved):
        write_rejected(client, "fact_payments", run_id, unresolved.to_dict("records"), "unresolved_customer_key")
    resolved = df.dropna(subset=["customer_key"]).copy()
    resolved["customer_key"] = resolved["customer_key"].astype(int)
    resolved["date_key"] = pd.to_datetime(resolved["order_purchase_timestamp"]).dt.strftime("%Y%m%d").astype(int)

    out_cols = ["order_id", "payment_sequential", "date_key", "customer_key",
                "payment_type", "payment_installments", "payment_value"]
    client.command("TRUNCATE TABLE IF EXISTS warehouse.fact_payments")
    client.insert_df("warehouse.fact_payments", resolved[out_cols])
    print(f"warehouse.fact_payments: loaded={len(resolved)} rejected={before - len(resolved)}")


def load_fact_reviews(client):
    run_id = str(uuid.uuid4())
    reviews = client.query_df("SELECT * FROM staging.reviews")
    orders = client.query_df("SELECT order_id, customer_id FROM staging.orders")
    cust_map = _customer_key_map(client)

    df = reviews.merge(orders, on="order_id", how="left")
    before = len(df)
    df = df.merge(cust_map, on="customer_id", how="left")

    unresolved = df[df["customer_key"].isna()]
    if len(unresolved):
        write_rejected(client, "fact_reviews", run_id, unresolved.to_dict("records"), "unresolved_customer_key")
    resolved = df.dropna(subset=["customer_key"]).copy()
    resolved["customer_key"] = resolved["customer_key"].astype(int)
    resolved["date_key"] = pd.to_datetime(resolved["review_creation_date"]).dt.strftime("%Y%m%d").astype(int)
    resolved["response_time_hours"] = (
        (pd.to_datetime(resolved["review_answer_timestamp"]) - pd.to_datetime(resolved["review_creation_date"]))
        .dt.total_seconds() / 3600
    ).astype(int)

    out_cols = ["review_id", "order_id", "date_key", "customer_key",
                "review_score", "has_comment", "response_time_hours"]
    client.command("TRUNCATE TABLE IF EXISTS warehouse.fact_reviews")
    client.insert_df("warehouse.fact_reviews", resolved[out_cols])
    print(f"warehouse.fact_reviews: loaded={len(resolved)} rejected={before - len(resolved)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    client = get_client()

    if args.all:
        load_fact_orders(client)
        load_fact_order_items(client)
        load_fact_payments(client)
        load_fact_reviews(client)


if __name__ == "__main__":
    main()

"""
clean.py - Raw -> Staging.

For each raw table:
  1. pull rows from ClickHouse raw.<table> as a DataFrame
  2. run validation.py checks -> good rows / rejected rows
  3. cast + standardize the good rows (types, trimming, dates)
  4. insert good rows into staging.<table>
  5. insert rejected rows into raw.rejected_rows
  6. print a data-quality report

Run in dependency order (parents before children, since FK validation
needs the parent already sitting in staging):
    python clean.py --all
"""
import argparse
import sys
import uuid

import clickhouse_connect
import pandas as pd

sys.path.append("../ingestion")
import config
import validation as V


def get_client():
    return clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
    )


def write_rejected(client, table_name, run_id, rejected):
    if not rejected:
        return
    rows = [[run_id, table_name, r["raw_row_json"], r["rejection_reason"]] for r in rejected]
    client.insert(
        "raw.rejected_rows",
        rows,
        column_names=["run_id", "source_table", "raw_row_json", "rejection_reason"],
    )


def clean_category_translation(client):
    df = client.query_df("SELECT * FROM raw.category_translation")
    df = df.drop_duplicates(subset=["product_category_name"])
    client.command("TRUNCATE TABLE IF EXISTS staging.category_translation")
    client.insert_df("staging.category_translation",
                      df[["product_category_name", "product_category_name_english"]])
    print(f"staging.category_translation: {len(df)} rows")


def clean_sellers(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.sellers")
    good, rejected = V.validate_sellers(df)
    write_rejected(client, "sellers", run_id, rejected)
    print(V.quality_report("sellers", len(df), len(good), rejected))

    if len(good):
        good = good.drop_duplicates(subset=["seller_id"])
        good["seller_city"] = good["seller_city"].str.strip().str.title()
        client.command("TRUNCATE TABLE IF EXISTS staging.sellers")
        client.insert_df("staging.sellers",
                          good[["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]])
    print(f"staging.sellers: {len(good)} rows")


def clean_products(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.products")
    good, rejected = V.validate_products(df)
    write_rejected(client, "products", run_id, rejected)
    print(V.quality_report("products", len(df), len(good), rejected))

    if len(good):
        good = good.drop_duplicates(subset=["product_id"])
        good["product_category_name"] = good["product_category_name"].replace("", "unknown")
        for col, out_type in [
            ("product_photos_qty", "Int64"), ("product_weight_g", "Int64"),
            ("product_length_cm", "Int64"), ("product_height_cm", "Int64"),
            ("product_width_cm", "Int64"),
        ]:
            good[col] = pd.to_numeric(good[col], errors="coerce").astype(out_type)
        good["product_photos_qty"] = good["product_photos_qty"].fillna(0)
        client.command("TRUNCATE TABLE IF EXISTS staging.products")
        client.insert_df(
            "staging.products",
            good[["product_id", "product_category_name", "product_photos_qty",
                  "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm"]],
        )
    print(f"staging.products: {len(good)} rows")


def clean_customers(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.customers")
    good, rejected = V.validate_customers(df)
    write_rejected(client, "customers", run_id, rejected)
    print(V.quality_report("customers", len(df), len(good), rejected))

    if len(good):
        good = good.drop_duplicates(subset=["customer_id"])
        good["customer_city"] = good["customer_city"].str.strip().str.title()
        client.command("TRUNCATE TABLE IF EXISTS staging.customers")
        client.insert_df(
            "staging.customers",
            good[["customer_id", "customer_unique_id", "customer_zip_code_prefix",
                  "customer_city", "customer_state"]],
        )
    print(f"staging.customers: {len(good)} rows")


def clean_orders(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.orders")
    valid_customers = set(client.query_df("SELECT customer_id FROM staging.customers")["customer_id"])
    good, rejected = V.validate_orders(df, valid_customers)
    write_rejected(client, "orders", run_id, rejected)
    print(V.quality_report("orders", len(df), len(good), rejected))

    if len(good):
        good = good.drop_duplicates(subset=["order_id"])
        for col in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
                    "order_delivered_customer_date", "order_estimated_delivery_date"]:
            good[col] = pd.to_datetime(good[col], errors="coerce")
        # estimated delivery date must always be present; the rest can be null
        # (order not yet approved/shipped/delivered is normal, not bad data)
        good = good.dropna(subset=["order_estimated_delivery_date", "order_purchase_timestamp"])
        client.command("TRUNCATE TABLE IF EXISTS staging.orders")
        client.insert_df(
            "staging.orders",
            good[["order_id", "customer_id", "order_status", "order_purchase_timestamp",
                  "order_approved_at", "order_delivered_carrier_date",
                  "order_delivered_customer_date", "order_estimated_delivery_date"]],
        )
    print(f"staging.orders: {len(good)} rows")


def clean_order_items(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.order_items")
    valid_orders = set(client.query_df("SELECT order_id FROM staging.orders")["order_id"])
    valid_products = set(client.query_df("SELECT product_id FROM staging.products")["product_id"])
    valid_sellers = set(client.query_df("SELECT seller_id FROM staging.sellers")["seller_id"])
    good, rejected = V.validate_order_items(df, valid_orders, valid_products, valid_sellers)
    write_rejected(client, "order_items", run_id, rejected)
    print(V.quality_report("order_items", len(df), len(good), rejected))

    if len(good):
        good["order_item_id"] = good["order_item_id"].astype(int)
        good["shipping_limit_date"] = pd.to_datetime(good["shipping_limit_date"], errors="coerce")
        good["price"] = good["price"].astype(float)
        good["freight_value"] = good["freight_value"].astype(float)
        good = good.drop_duplicates(subset=["order_id", "order_item_id"])
        client.command("TRUNCATE TABLE IF EXISTS staging.order_items")
        client.insert_df(
            "staging.order_items",
            good[["order_id", "order_item_id", "product_id", "seller_id",
                  "shipping_limit_date", "price", "freight_value"]],
        )
    print(f"staging.order_items: {len(good)} rows")


def clean_payments(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.payments")
    valid_orders = set(client.query_df("SELECT order_id FROM staging.orders")["order_id"])
    good, rejected = V.validate_payments(df, valid_orders)
    write_rejected(client, "payments", run_id, rejected)
    print(V.quality_report("payments", len(df), len(good), rejected))

    if len(good):
        good["payment_sequential"] = good["payment_sequential"].astype(int)
        good["payment_installments"] = pd.to_numeric(good["payment_installments"], errors="coerce").fillna(1).astype(int)
        good["payment_value"] = good["payment_value"].astype(float)
        good = good.drop_duplicates(subset=["order_id", "payment_sequential"])
        client.command("TRUNCATE TABLE IF EXISTS staging.payments")
        client.insert_df(
            "staging.payments",
            good[["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"]],
        )
    print(f"staging.payments: {len(good)} rows")


def clean_reviews(client):
    run_id = str(uuid.uuid4())
    df = client.query_df("SELECT * FROM raw.reviews")
    valid_orders = set(client.query_df("SELECT order_id FROM staging.orders")["order_id"])
    good, rejected = V.validate_reviews(df, valid_orders)
    write_rejected(client, "reviews", run_id, rejected)
    print(V.quality_report("reviews", len(df), len(good), rejected))

    if len(good):
        good["review_score"] = good["review_score"].astype(int)
        good["has_comment"] = (
            (good["review_comment_title"].str.strip() != "") |
            (good["review_comment_message"].str.strip() != "")
        ).astype(int)
        good["review_creation_date"] = pd.to_datetime(good["review_creation_date"], errors="coerce")
        good["review_answer_timestamp"] = pd.to_datetime(good["review_answer_timestamp"], errors="coerce")
        good = good.dropna(subset=["review_creation_date", "review_answer_timestamp"])
        good = good.drop_duplicates(subset=["review_id"])
        client.command("TRUNCATE TABLE IF EXISTS staging.reviews")
        client.insert_df(
            "staging.reviews",
            good[["review_id", "order_id", "review_score", "has_comment",
                  "review_creation_date", "review_answer_timestamp"]],
        )
    print(f"staging.reviews: {len(good)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    client = get_client()

    if args.all:
        # order matters: parents before children (FK validation needs parents in staging first)
        clean_category_translation(client)
        clean_sellers(client)
        clean_products(client)
        clean_customers(client)
        clean_orders(client)
        clean_order_items(client)
        clean_payments(client)
        clean_reviews(client)


if __name__ == "__main__":
    main()

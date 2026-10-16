"""
validation.py - Row-level validation rules, raw -> staging.

Each validate_* function takes a raw DataFrame (all strings) and returns
(good_df, rejected_list). rejected_list items are dicts with the original
row (as JSON) and a reason, ready to insert into raw.rejected_rows.
"""
import json

import pandas as pd


def _split(df, is_bad_mask, reason):
    bad = df[is_bad_mask]
    good = df[~is_bad_mask]
    rejected = [
        {"raw_row_json": json.dumps(row.to_dict(), default=str), "rejection_reason": reason}
        for _, row in bad.iterrows()
    ]
    return good, rejected


def quality_report(table_name, total, good_count, rejected):
    pass_rate = (good_count / total * 100) if total else 0
    return f"{table_name}: {total} read, {good_count} passed ({pass_rate:.1f}%), {len(rejected)} rejected"


def validate_customers(df):
    rejected = []
    bad_id = df["customer_id"].isna() | (df["customer_id"].str.strip() == "")
    g, r = _split(df, bad_id, "missing customer_id")
    rejected += r
    df = g

    bad_unique = df["customer_unique_id"].isna() | (df["customer_unique_id"].str.strip() == "")
    g, r = _split(df, bad_unique, "missing customer_unique_id")
    rejected += r
    return g, rejected


def validate_orders(df, valid_customers):
    rejected = []
    bad_id = df["order_id"].isna() | (df["order_id"].str.strip() == "")
    g, r = _split(df, bad_id, "missing order_id")
    rejected += r
    df = g

    bad_customer = ~df["customer_id"].isin(valid_customers)
    g, r = _split(df, bad_customer, "customer_id not found in staging.customers")
    rejected += r
    df = g

    bad_purchase_ts = pd.to_datetime(df["order_purchase_timestamp"], errors="coerce").isna()
    g, r = _split(df, bad_purchase_ts, "unparseable order_purchase_timestamp")
    rejected += r
    return g, rejected


def validate_order_items(df, valid_orders, valid_products, valid_sellers):
    rejected = []
    bad_order = ~df["order_id"].isin(valid_orders)
    g, r = _split(df, bad_order, "order_id not found in staging.orders")
    rejected += r
    df = g

    bad_product = ~df["product_id"].isin(valid_products)
    g, r = _split(df, bad_product, "product_id not found in staging.products")
    rejected += r
    df = g

    bad_seller = ~df["seller_id"].isin(valid_sellers)
    g, r = _split(df, bad_seller, "seller_id not found in staging.sellers")
    rejected += r
    df = g

    bad_price = pd.to_numeric(df["price"], errors="coerce").isna() | (pd.to_numeric(df["price"], errors="coerce") < 0)
    g, r = _split(df, bad_price, "invalid or negative price")
    rejected += r
    return g, rejected


def validate_payments(df, valid_orders):
    rejected = []
    bad_order = ~df["order_id"].isin(valid_orders)
    g, r = _split(df, bad_order, "order_id not found in staging.orders")
    rejected += r
    df = g

    bad_value = pd.to_numeric(df["payment_value"], errors="coerce").isna()
    g, r = _split(df, bad_value, "invalid payment_value")
    rejected += r
    return g, rejected


def validate_reviews(df, valid_orders):
    rejected = []
    bad_order = ~df["order_id"].isin(valid_orders)
    g, r = _split(df, bad_order, "order_id not found in staging.orders")
    rejected += r
    df = g

    scores = pd.to_numeric(df["review_score"], errors="coerce")
    bad_score = scores.isna() | (scores < 1) | (scores > 5)
    g, r = _split(df, bad_score, "review_score outside 1-5")
    rejected += r
    return g, rejected


def validate_products(df):
    rejected = []
    bad_id = df["product_id"].isna() | (df["product_id"].str.strip() == "")
    g, r = _split(df, bad_id, "missing product_id")
    rejected += r
    return g, rejected


def validate_sellers(df):
    rejected = []
    bad_id = df["seller_id"].isna() | (df["seller_id"].str.strip() == "")
    g, r = _split(df, bad_id, "missing seller_id")
    rejected += r
    return g, rejected

"""
Data quality tests - run after loading facts/dims.

Run:
    pytest tests/test_data_quality.py -v

Requires ClickHouse running and the pipeline already having been run once:
load_raw.py --all -> clean.py --all -> load_dimensions.py --all -> load_facts.py --all
"""
import sys

import clickhouse_connect
import pytest

sys.path.append("../ingestion")
import config


@pytest.fixture(scope="module")
def client():
    return clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
    )


def scalar(client, sql):
    return client.query(sql).result_rows[0][0]


def test_no_negative_prices(client):
    n = scalar(client, "SELECT count(*) FROM warehouse.fact_order_items WHERE price < 0 OR freight_value < 0")
    assert n == 0


def test_no_duplicate_order_items(client):
    n = scalar(client, """
        SELECT count(*) FROM (
            SELECT order_id, order_item_id, count(*) c FROM warehouse.fact_order_items
            GROUP BY order_id, order_item_id HAVING c > 1
        )
    """)
    assert n == 0


def test_no_orphan_customer_keys_in_order_items(client):
    n = scalar(client, """
        SELECT count(*) FROM warehouse.fact_order_items f
        LEFT JOIN warehouse.dim_customer c ON f.customer_key = c.customer_key
        WHERE c.customer_key IS NULL
    """)
    assert n == 0


def test_no_orphan_product_keys(client):
    n = scalar(client, """
        SELECT count(*) FROM warehouse.fact_order_items f
        LEFT JOIN warehouse.dim_product p ON f.product_key = p.product_key
        WHERE p.product_key IS NULL
    """)
    assert n == 0


def test_no_orphan_seller_keys(client):
    n = scalar(client, """
        SELECT count(*) FROM warehouse.fact_order_items f
        LEFT JOIN warehouse.dim_seller s ON f.seller_key = s.seller_key
        WHERE s.seller_key IS NULL
    """)
    assert n == 0


def test_dim_customer_scd2_only_one_current_row_per_person(client):
    n = scalar(client, """
        SELECT count(*) FROM (
            SELECT customer_unique_id, count(*) c FROM warehouse.dim_customer
            WHERE is_current = 1 GROUP BY customer_unique_id HAVING c > 1
        )
    """)
    assert n == 0


def test_review_scores_within_range(client):
    n = scalar(client, "SELECT count(*) FROM warehouse.fact_reviews WHERE review_score < 1 OR review_score > 5")
    assert n == 0


def test_reconciliation_raw_vs_warehouse_order_count(client):
    """Sanity check: warehouse order count shouldn't wildly diverge from raw."""
    raw_orders = scalar(client, "SELECT count(DISTINCT order_id) FROM raw.orders")
    wh_orders = scalar(client, "SELECT count(DISTINCT order_id) FROM warehouse.fact_orders")
    # allow some loss to validation/quarantine, but not more than ~10%
    assert wh_orders >= raw_orders * 0.90

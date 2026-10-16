"""
load_raw.py - Extract + Load into the raw layer.

Reads every CSV in data/raw, tags each row with its source file, and loads
it as-is (all Strings) into raw.<table>. Every run writes a row to
raw.pipeline_run_log so you have an audit trail.

Rerunnable: re-running with the same file will re-insert (raw layer is
append-only/log-like by design - de-duplication happens in staging).

Usage:
    python load_raw.py --file customers.csv
    python load_raw.py --all
"""
import argparse
import csv
import os
import uuid
from datetime import datetime

import clickhouse_connect
import config

TABLE_MAP = {
    "customers.csv": "customers",
    "geolocation.csv": "geolocation",
    "orders.csv": "orders",
    "order_items.csv": "order_items",
    "payments.csv": "payments",
    "reviews.csv": "reviews",
    "products.csv": "products",
    "sellers.csv": "sellers",
    "category_translation.csv": "category_translation",
}


def get_client():
    return clickhouse_connect.get_client(
        host=config.CLICKHOUSE_HOST,
        port=config.CLICKHOUSE_PORT,
        username=config.CLICKHOUSE_USER,
        password=config.CLICKHOUSE_PASSWORD,
    )


def load_file(client, filename):
    table = TABLE_MAP[filename]
    path = os.path.join(config.RAW_DATA_DIR, filename)
    run_id = str(uuid.uuid4())
    started_at = datetime.utcnow()

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = reader.fieldnames

    rows_read = len(rows)
    data = [
        [*(r[c] for c in cols), filename]
        for r in rows
    ]
    insert_cols = cols + ["_source_file"]

    rows_loaded, status = 0, "success"
    try:
        client.insert(f"raw.{table}", data, column_names=insert_cols)
        rows_loaded = rows_read
    except Exception as e:
        status = "failed"
        print(f"  ERROR loading {filename}: {e}")

    finished_at = datetime.utcnow()
    client.insert(
        "raw.pipeline_run_log",
        [[run_id, table, filename, started_at, finished_at, rows_read, rows_loaded, rows_read - rows_loaded, status]],
        column_names=["run_id", "source_table", "source_file", "started_at", "finished_at",
                      "rows_read", "rows_loaded", "rows_rejected", "status"],
    )
    print(f"[{status}] {filename}: read={rows_read} loaded={rows_loaded}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="single filename, e.g. customers.csv")
    ap.add_argument("--all", action="store_true", help="load every mapped file")
    args = ap.parse_args()

    client = get_client()

    if args.all:
        for filename in TABLE_MAP:
            load_file(client, filename)
    elif args.file:
        load_file(client, args.file)
    else:
        print("Pass --file <name>.csv or --all")


if __name__ == "__main__":
    main()

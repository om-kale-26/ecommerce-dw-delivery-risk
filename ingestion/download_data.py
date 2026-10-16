"""
download_data.py - Pull the real Olist Brazilian E-Commerce dataset from Kaggle
into data/raw, and rename files to the short names load_raw.py expects.

One-time setup (do this once, on your own machine, not in a container):
    1. Create a Kaggle account -> https://www.kaggle.com/settings -> "Create New Token"
       This downloads kaggle.json.
    2. Place it at C:\\Users\\<you>\\.kaggle\\kaggle.json (Windows)
       or ~/.kaggle/kaggle.json (Mac/Linux).
    3. pip install kaggle --break-system-packages   (already in requirements.txt)

Usage:
    python download_data.py
"""
import os
import shutil
import zipfile

DATASET = "olistbr/brazilian-ecommerce"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# Kaggle's real filenames -> the short names our TABLE_MAP uses
RENAME_MAP = {
    "olist_customers_dataset.csv": "customers.csv",
    "olist_geolocation_dataset.csv": "geolocation.csv",
    "olist_orders_dataset.csv": "orders.csv",
    "olist_order_items_dataset.csv": "order_items.csv",
    "olist_order_payments_dataset.csv": "payments.csv",
    "olist_order_reviews_dataset.csv": "reviews.csv",
    "olist_products_dataset.csv": "products.csv",
    "olist_sellers_dataset.csv": "sellers.csv",
    "product_category_name_translation.csv": "category_translation.csv",
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # Imported here so the script gives a friendly error if kaggle.json isn't set up yet
    from kaggle.api.kaggle_api_extended import KaggleApi

    api = KaggleApi()
    api.authenticate()

    print(f"Downloading {DATASET} ...")
    api.dataset_download_files(DATASET, path=OUT_DIR, unzip=False)

    zip_path = os.path.join(OUT_DIR, "brazilian-ecommerce.zip")
    print("Unzipping...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(OUT_DIR)
    os.remove(zip_path)

    print("Renaming files...")
    for original, short in RENAME_MAP.items():
        src = os.path.join(OUT_DIR, original)
        dst = os.path.join(OUT_DIR, short)
        if os.path.exists(src):
            shutil.move(src, dst)
            print(f"  {original} -> {short}")
        elif not os.path.exists(dst):
            print(f"  WARNING: expected file not found: {original}")

    print(f"\nDone. Files are in {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()

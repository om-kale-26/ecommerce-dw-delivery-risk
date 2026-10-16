-- Gold layer: business-ready star schema.

CREATE DATABASE IF NOT EXISTS warehouse;

-- dim_date: fully pre-populated, deterministic (covers 2016-01-01 .. 2018-12-31,
-- the real span of the Olist dataset). Loaded once by load_dimensions.py --dates
CREATE TABLE IF NOT EXISTS warehouse.dim_date
(
    date_key    UInt32,     -- yyyymmdd
    date        Date,
    day         UInt8,
    month       UInt8,
    month_name  LowCardinality(String),
    quarter     UInt8,
    year        UInt16,
    weekday     LowCardinality(String),
    is_weekend  UInt8
)
ENGINE = MergeTree
ORDER BY date_key;

-- dim_customer: SLOWLY CHANGING DIMENSION TYPE 2, keyed on customer_unique_id -
-- the real human. Olist mints a fresh customer_id per order, so customer_id
-- itself is NOT the right SCD business key; customer_unique_id is.
-- A new version row is written whenever a person's city/state changes
-- across their orders.
CREATE TABLE IF NOT EXISTS warehouse.dim_customer
(
    customer_key        UInt64,   -- surrogate key, unique per row/version
    customer_unique_id  String,   -- business key, repeats across versions
    city                String,
    state                LowCardinality(String),
    zip_code_prefix       String,
    effective_from       DateTime,
    effective_to         Nullable(DateTime),  -- NULL = current version
    is_current            UInt8
)
ENGINE = MergeTree
ORDER BY (customer_unique_id, effective_from);

CREATE TABLE IF NOT EXISTS warehouse.dim_category
(
    category_key            UInt32,
    category_name_pt        String,
    category_name_english   String
)
ENGINE = MergeTree
ORDER BY category_key;

CREATE TABLE IF NOT EXISTS warehouse.dim_product
(
    product_key         UInt64,
    product_id          String,
    category_key        UInt32,
    photos_qty          UInt16,
    weight_g            Nullable(UInt32),
    length_cm           Nullable(UInt16),
    height_cm           Nullable(UInt16),
    width_cm            Nullable(UInt16)
)
ENGINE = MergeTree
ORDER BY product_key;

-- dim_seller: Olist is a marketplace - sellers are a first-class dimension,
-- distinct from customers, with their own geography.
CREATE TABLE IF NOT EXISTS warehouse.dim_seller
(
    seller_key          UInt64,
    seller_id           String,
    city                String,
    state               LowCardinality(String),
    zip_code_prefix     String
)
ENGINE = MergeTree
ORDER BY seller_key;

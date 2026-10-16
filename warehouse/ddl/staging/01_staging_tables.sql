-- Staging / Silver layer: typed, deduplicated, standardized.
-- Rows that fail casting/validation in clean.py never make it here -
-- they land in raw.rejected_rows instead.

CREATE DATABASE IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.customers
(
    customer_id                String,
    customer_unique_id         String,
    customer_zip_code_prefix   String,
    customer_city              String,
    customer_state             LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY customer_id;

CREATE TABLE IF NOT EXISTS staging.orders
(
    order_id                        String,
    customer_id                     String,
    order_status                    LowCardinality(String),
    order_purchase_timestamp        DateTime,
    order_approved_at               Nullable(DateTime),
    order_delivered_carrier_date    Nullable(DateTime),
    order_delivered_customer_date   Nullable(DateTime),
    order_estimated_delivery_date   DateTime
)
ENGINE = MergeTree
ORDER BY order_id;

CREATE TABLE IF NOT EXISTS staging.order_items
(
    order_id             String,
    order_item_id        UInt16,
    product_id           String,
    seller_id            String,
    shipping_limit_date  DateTime,
    price                Decimal(12,2),
    freight_value        Decimal(12,2)
)
ENGINE = MergeTree
ORDER BY (order_id, order_item_id);

CREATE TABLE IF NOT EXISTS staging.payments
(
    order_id             String,
    payment_sequential   UInt16,
    payment_type         LowCardinality(String),
    payment_installments UInt16,
    payment_value        Decimal(12,2)
)
ENGINE = MergeTree
ORDER BY (order_id, payment_sequential);

CREATE TABLE IF NOT EXISTS staging.reviews
(
    review_id                 String,
    order_id                  String,
    review_score              UInt8,
    has_comment                UInt8,   -- derived: 1 if title or message non-empty
    review_creation_date      DateTime,
    review_answer_timestamp   DateTime
)
ENGINE = MergeTree
ORDER BY review_id;

CREATE TABLE IF NOT EXISTS staging.products
(
    product_id              String,
    product_category_name   String,
    product_photos_qty      UInt16,
    product_weight_g        Nullable(UInt32),
    product_length_cm       Nullable(UInt16),
    product_height_cm       Nullable(UInt16),
    product_width_cm        Nullable(UInt16)
)
ENGINE = MergeTree
ORDER BY product_id;

CREATE TABLE IF NOT EXISTS staging.sellers
(
    seller_id               String,
    seller_zip_code_prefix  String,
    seller_city             String,
    seller_state            LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY seller_id;

CREATE TABLE IF NOT EXISTS staging.category_translation
(
    product_category_name          String,
    product_category_name_english  String
)
ENGINE = MergeTree
ORDER BY product_category_name;

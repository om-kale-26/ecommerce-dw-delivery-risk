-- Fact tables. Grain is documented explicitly for each - always be able to
-- say "one row in this table represents ___".
--
-- NOTE: Olist has no returns dataset (unlike the synthetic version of this
-- project). Instead it has rich order-lifecycle timestamps and review
-- scores, which are arguably more interesting - fact_orders below captures
-- delivery performance (on-time vs late, cancellations) as the analytical
-- stand-in for "what went wrong with an order".

-- GRAIN: one row = one order (order-level lifecycle + delivery performance)
CREATE TABLE IF NOT EXISTS warehouse.fact_orders
(
    order_id                    String,
    date_key_purchase           UInt32,
    customer_key                UInt64,
    order_status                LowCardinality(String),
    purchase_ts                 DateTime,
    approved_at                 Nullable(DateTime),
    delivered_carrier_at        Nullable(DateTime),
    delivered_customer_at       Nullable(DateTime),
    estimated_delivery_at       DateTime,
    delivery_days               Nullable(Int32),  -- delivered_customer_at - purchase_ts, in days
    delay_vs_estimate_days      Nullable(Int32),  -- delivered_customer_at - estimated_delivery_at (positive = late)
    is_late                     UInt8,            -- 1 if delivered after estimate
    is_delivered                UInt8,
    is_canceled                 UInt8,
    _loaded_at                  DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY intDiv(date_key_purchase, 100)
ORDER BY (date_key_purchase, customer_key);

-- GRAIN: one row = one order line (one product within one order, one seller)
CREATE TABLE IF NOT EXISTS warehouse.fact_order_items
(
    order_id          String,
    order_item_id     UInt16,
    date_key          UInt32,     -- purchase date
    customer_key      UInt64,
    product_key       UInt64,
    seller_key        UInt64,
    price             Decimal(12,2),
    freight_value     Decimal(12,2),
    total_amount      Decimal(14,2),  -- price + freight_value
    _loaded_at        DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY intDiv(date_key, 100)
ORDER BY (date_key, product_key, customer_key);

-- GRAIN: one row = one payment attempt (installment line) against one order
CREATE TABLE IF NOT EXISTS warehouse.fact_payments
(
    order_id              String,
    payment_sequential    UInt16,
    date_key              UInt32,   -- purchase date of the parent order
    customer_key          UInt64,
    payment_type          LowCardinality(String),
    payment_installments  UInt16,
    payment_value         Decimal(12,2),
    _loaded_at            DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (date_key, customer_key);

-- GRAIN: one row = one customer review of one order
CREATE TABLE IF NOT EXISTS warehouse.fact_reviews
(
    review_id                String,
    order_id                 String,
    date_key                 UInt32,   -- review creation date
    customer_key             UInt64,
    review_score             UInt8,
    has_comment              UInt8,
    response_time_hours      Nullable(Int32),  -- answer_timestamp - creation_date
    _loaded_at               DateTime DEFAULT now()
)
ENGINE = MergeTree
ORDER BY (date_key, review_score);

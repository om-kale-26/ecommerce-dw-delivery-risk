-- One row per DELIVERED order, using only information known at purchase time.
-- Label: late_delivery = 1 if the order arrived on a later DATE than promised.
-- Excluded on purpose (leakage): actual delivery dates, carrier date, review score/comment.

WITH items AS
(
    SELECT
        order_id,
        count()                  AS item_count,
        uniqExact(seller_id)     AS seller_count,
        uniqExact(product_id)    AS product_count,
        sum(price)               AS items_value,
        sum(freight_value)       AS freight_total,
        min(seller_id)           AS main_seller_id
    FROM staging.order_items
    GROUP BY order_id
),
prod AS
(
    SELECT
        i.order_id AS order_id,
        sum(p.product_weight_g)                                           AS total_weight_g,
        sum(p.product_length_cm * p.product_height_cm * p.product_width_cm) AS total_volume_cm3
    FROM staging.order_items AS i
    LEFT JOIN staging.products AS p ON p.product_id = i.product_id
    GROUP BY i.order_id
)
SELECT
    o.order_id                                                              AS order_id,
    o.order_purchase_timestamp                                              AS purchase_ts,
    toDayOfWeek(o.order_purchase_timestamp)                                 AS purchase_dow,
    toHour(o.order_purchase_timestamp)                                      AS purchase_hour,
    toMonth(o.order_purchase_timestamp)                                     AS purchase_month,
    dateDiff('day', toDate(o.order_purchase_timestamp),
                    toDate(o.order_estimated_delivery_date))                AS promised_days,
    it.item_count                                                           AS item_count,
    it.seller_count                                                         AS seller_count,
    it.product_count                                                        AS product_count,
    it.items_value                                                          AS items_value,
    it.freight_total                                                        AS freight_total,
    it.freight_total / nullIf(it.items_value, 0)                            AS freight_ratio,
    pr.total_weight_g                                                       AS total_weight_g,
    pr.total_volume_cm3                                                     AS total_volume_cm3,
    c.customer_state                                                        AS customer_state,
    s.seller_state                                                          AS seller_state,
    toUInt8(c.customer_state != '' AND c.customer_state = s.seller_state)   AS same_state,
    toUInt8(toDate(o.order_delivered_customer_date)
          > toDate(o.order_estimated_delivery_date))                        AS label
FROM staging.orders AS o
INNER JOIN items AS it ON it.order_id = o.order_id
LEFT  JOIN prod  AS pr ON pr.order_id = o.order_id
LEFT  JOIN staging.customers AS c ON c.customer_id = o.customer_id
LEFT  JOIN staging.sellers   AS s ON s.seller_id   = it.main_seller_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date  > toDateTime('2000-01-01')
  AND o.order_estimated_delivery_date  > toDateTime('2000-01-01')
  AND o.order_purchase_timestamp       > toDateTime('2000-01-01')
  AND o.order_delivered_customer_date >= o.order_purchase_timestamp
LIMIT 1 BY o.order_id

-- ============================================================
-- Business Analytics Query Library — Olist E-Commerce Data Warehouse
-- Run against the `warehouse` database in ClickHouse (via DBeaver).
-- These are also the source queries for the Power BI dashboard -
-- see powerbi/README.md for which ones feed which visuals.
-- ============================================================

-- ------------------------------------------------------------
-- 1) SALES OVERVIEW
-- ------------------------------------------------------------

-- Q1: Revenue, orders, and units by month
SELECT
    d.year, d.month, d.month_name,
    round(sum(f.total_amount), 2) AS revenue,
    count(DISTINCT f.order_id)    AS orders,
    count(*)                       AS units
FROM warehouse.fact_order_items f
JOIN warehouse.dim_date d ON f.date_key = d.date_key
GROUP BY d.year, d.month, d.month_name
ORDER BY d.year, d.month;

-- Q2: Average Order Value (AOV)
SELECT round(sum(total_amount) / count(DISTINCT order_id), 2) AS aov
FROM warehouse.fact_order_items;

-- Q3: Month-over-month revenue growth (window function: LAG)
SELECT
    year, month, revenue,
    round(revenue - lagInFrame(revenue) OVER (ORDER BY year, month), 2) AS mom_change,
    round((revenue - lagInFrame(revenue) OVER (ORDER BY year, month))
          / lagInFrame(revenue) OVER (ORDER BY year, month) * 100, 2)   AS mom_growth_pct
FROM (
    SELECT d.year, d.month, sum(f.total_amount) AS revenue
    FROM warehouse.fact_order_items f
    JOIN warehouse.dim_date d ON f.date_key = d.date_key
    GROUP BY d.year, d.month
)
ORDER BY year, month;

-- Q4: Running (cumulative) revenue total across each year
SELECT
    year, month,
    sum(sum(total_amount)) OVER (PARTITION BY year ORDER BY month) AS running_revenue
FROM warehouse.fact_order_items f
JOIN warehouse.dim_date d ON f.date_key = d.date_key
GROUP BY year, month
ORDER BY year, month;

-- ------------------------------------------------------------
-- 2) CATEGORY & SELLER PERFORMANCE
-- ------------------------------------------------------------

-- Q5: Top 15 categories by revenue (with RANK)
SELECT
    c.category_name_english,
    round(sum(f.total_amount), 2) AS revenue,
    count(*) AS units_sold,
    rank() OVER (ORDER BY sum(f.total_amount) DESC) AS revenue_rank
FROM warehouse.fact_order_items f
JOIN warehouse.dim_product p  ON f.product_key = p.product_key
JOIN warehouse.dim_category c ON p.category_key = c.category_key
GROUP BY c.category_name_english
ORDER BY revenue DESC
LIMIT 15;

-- Q6: Each category's share of total revenue (PERCENT_RANK-style share calc)
SELECT
    c.category_name_english,
    round(sum(f.total_amount), 2) AS revenue,
    round(sum(f.total_amount) * 100.0 / sum(sum(f.total_amount)) OVER (), 2) AS pct_of_total
FROM warehouse.fact_order_items f
JOIN warehouse.dim_product p  ON f.product_key = p.product_key
JOIN warehouse.dim_category c ON p.category_key = c.category_key
GROUP BY c.category_name_english
ORDER BY revenue DESC;

-- Q7: Top 10 sellers by revenue and order count
SELECT
    s.seller_id, s.city, s.state,
    round(sum(f.total_amount), 2) AS revenue,
    count(DISTINCT f.order_id)     AS orders
FROM warehouse.fact_order_items f
JOIN warehouse.dim_seller s ON f.seller_key = s.seller_key
GROUP BY s.seller_id, s.city, s.state
ORDER BY revenue DESC
LIMIT 10;

-- Q8: Revenue by seller state (good for a Power BI map visual)
SELECT s.state, round(sum(f.total_amount), 2) AS revenue, count(DISTINCT f.order_id) AS orders
FROM warehouse.fact_order_items f
JOIN warehouse.dim_seller s ON f.seller_key = s.seller_key
GROUP BY s.state
ORDER BY revenue DESC;

-- ------------------------------------------------------------
-- 3) CUSTOMER GEOGRAPHY & RFM SEGMENTATION
-- ------------------------------------------------------------

-- Q9: Revenue by customer state (map visual in Power BI)
SELECT dc.state, round(sum(f.total_amount), 2) AS revenue, count(DISTINCT f.order_id) AS orders
FROM warehouse.fact_order_items f
JOIN warehouse.dim_customer dc ON f.customer_key = dc.customer_key
GROUP BY dc.state
ORDER BY revenue DESC;

-- Q10: RFM segmentation (Recency, Frequency, Monetary) per unique customer
-- Recency = days since last order, relative to the dataset's latest order date
WITH last_order_date AS (
    SELECT max(purchase_ts) AS max_date FROM warehouse.fact_orders
),
customer_rfm AS (
    SELECT
        dc.customer_unique_id,
        dateDiff('day', max(fo.purchase_ts), (SELECT max_date FROM last_order_date)) AS recency_days,
        count(DISTINCT fo.order_id) AS frequency,
        round(sum(fi.total_amount), 2) AS monetary
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_customer dc ON fo.customer_key = dc.customer_key
    JOIN warehouse.fact_order_items fi ON fi.order_id = fo.order_id
    GROUP BY dc.customer_unique_id
)
SELECT
    customer_unique_id, recency_days, frequency, monetary,
    ntile(5) OVER (ORDER BY recency_days DESC) AS r_score,   -- 5 = most recent
    ntile(5) OVER (ORDER BY frequency ASC)     AS f_score,
    ntile(5) OVER (ORDER BY monetary ASC)      AS m_score
FROM customer_rfm
ORDER BY monetary DESC
LIMIT 100;

-- Q11: Repeat vs one-time customers, and revenue share
SELECT
    multiIf(order_count = 1, 'one-time', 'repeat') AS customer_type,
    count(*) AS customers,
    round(sum(total_spend), 2) AS revenue,
    round(sum(total_spend) * 100.0 / sum(sum(total_spend)) OVER (), 2) AS pct_of_revenue
FROM (
    SELECT dc.customer_unique_id,
           count(DISTINCT fo.order_id) AS order_count,
           sum(fi.total_amount) AS total_spend
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_customer dc ON fo.customer_key = dc.customer_key
    JOIN warehouse.fact_order_items fi ON fi.order_id = fo.order_id
    GROUP BY dc.customer_unique_id
)
GROUP BY customer_type;

-- Q12: Cohort retention - % of each signup-month cohort still ordering N months later
-- (cohort = month of a person's FIRST order)
WITH first_order AS (
    SELECT dc.customer_unique_id, min(toStartOfMonth(fo.purchase_ts)) AS cohort_month
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_customer dc ON fo.customer_key = dc.customer_key
    GROUP BY dc.customer_unique_id
),
activity AS (
    SELECT dc.customer_unique_id, toStartOfMonth(fo.purchase_ts) AS order_month
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_customer dc ON fo.customer_key = dc.customer_key
)
SELECT
    fo.cohort_month,
    dateDiff('month', fo.cohort_month, a.order_month) AS months_since_first_order,
    count(DISTINCT a.customer_unique_id) AS active_customers
FROM first_order fo
JOIN activity a ON a.customer_unique_id = fo.customer_unique_id
GROUP BY fo.cohort_month, months_since_first_order
ORDER BY fo.cohort_month, months_since_first_order;

-- ------------------------------------------------------------
-- 4) DELIVERY PERFORMANCE (Olist's signature analytical angle)
-- ------------------------------------------------------------

-- Q13: On-time vs late delivery rate by month
SELECT
    d.year, d.month,
    countIf(is_delivered = 1) AS delivered_orders,
    countIf(is_delivered = 1 AND is_late = 1) AS late_orders,
    round(countIf(is_delivered = 1 AND is_late = 1) * 100.0 / countIf(is_delivered = 1), 2) AS pct_late
FROM warehouse.fact_orders f
JOIN warehouse.dim_date d ON f.date_key_purchase = d.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;

-- Q14: Average delivery time and delay by customer state
SELECT
    dc.state,
    round(avg(f.delivery_days), 1) AS avg_delivery_days,
    round(avg(f.delay_vs_estimate_days), 1) AS avg_delay_vs_estimate,
    round(countIf(f.is_late = 1) * 100.0 / countIf(f.is_delivered = 1), 2) AS pct_late
FROM warehouse.fact_orders f
JOIN warehouse.dim_customer dc ON f.customer_key = dc.customer_key
WHERE f.is_delivered = 1
GROUP BY dc.state
ORDER BY avg_delivery_days DESC;

-- Q15: Order status funnel (how many orders end up in each status)
SELECT order_status, count(*) AS orders,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 2) AS pct_of_orders
FROM warehouse.fact_orders
GROUP BY order_status
ORDER BY orders DESC;

-- ------------------------------------------------------------
-- 5) REVIEWS & SATISFACTION
-- ------------------------------------------------------------

-- Q16: Review score distribution
SELECT review_score, count(*) AS reviews,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 2) AS pct
FROM warehouse.fact_reviews
GROUP BY review_score
ORDER BY review_score;

-- Q17: Does a late delivery hurt the review score? (correlation-style check)
SELECT
    multiIf(fo.is_late = 1, 'late', 'on-time or unknown') AS delivery_bucket,
    round(avg(fr.review_score), 2) AS avg_review_score,
    count(*) AS n_reviews
FROM warehouse.fact_reviews fr
JOIN warehouse.fact_orders fo ON fr.order_id = fo.order_id
WHERE fo.is_delivered = 1
GROUP BY delivery_bucket;

-- Q18: Average review score by category
SELECT
    c.category_name_english,
    round(avg(fr.review_score), 2) AS avg_review_score,
    count(*) AS n_reviews
FROM warehouse.fact_reviews fr
JOIN warehouse.fact_order_items foi ON fr.order_id = foi.order_id
JOIN warehouse.dim_product p  ON foi.product_key = p.product_key
JOIN warehouse.dim_category c ON p.category_key = c.category_key
GROUP BY c.category_name_english
HAVING n_reviews >= 30
ORDER BY avg_review_score ASC
LIMIT 15;

-- ------------------------------------------------------------
-- 6) PAYMENTS
-- ------------------------------------------------------------

-- Q19: Revenue and order share by payment type
SELECT payment_type,
       round(sum(payment_value), 2) AS total_paid,
       count(DISTINCT order_id) AS orders,
       round(avg(payment_installments), 1) AS avg_installments
FROM warehouse.fact_payments
GROUP BY payment_type
ORDER BY total_paid DESC;

-- Q20: Installment count distribution for credit_card payments
SELECT payment_installments, count(*) AS payments
FROM warehouse.fact_payments
WHERE payment_type = 'credit_card'
GROUP BY payment_installments
ORDER BY payment_installments;

-- ------------------------------------------------------------
-- 7) DATA QUALITY / PIPELINE HEALTH (worth screenshotting for LinkedIn too)
-- ------------------------------------------------------------

-- Q21: Latest pipeline run summary per table
SELECT source_table, source_file, rows_read, rows_loaded, rows_rejected, status, finished_at
FROM raw.pipeline_run_log
ORDER BY finished_at DESC
LIMIT 20;

-- Q22: Rejection reasons breakdown
SELECT source_table, rejection_reason, count(*) AS n
FROM raw.rejected_rows
GROUP BY source_table, rejection_reason
ORDER BY n DESC;

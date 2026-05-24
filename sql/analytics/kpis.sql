-- ============================================================
-- Supply Chain KPIs (MySQL 8.0): Analytical views on the star schema
-- Run AFTER the ingestion script has populated fact_orders
-- ============================================================

USE supply_chain;

DROP VIEW IF EXISTS vw_kpi_summary;
DROP VIEW IF EXISTS vw_shipping_mode_scorecard;
DROP VIEW IF EXISTS vw_market_performance;
DROP VIEW IF EXISTS vw_category_demand_monthly;
DROP VIEW IF EXISTS vw_top_problem_routes;
DROP VIEW IF EXISTS vw_customer_segment_profitability;

-- ============================================================
-- 1. HEADLINE KPI SUMMARY
-- The numbers an Ops Director would want on the front page
-- ============================================================
CREATE VIEW vw_kpi_summary AS
SELECT
    COUNT(*)                                                                  AS total_order_lines,
    COUNT(DISTINCT order_id)                                                  AS total_orders,

    -- OTIF: on-time AND not cancelled
    ROUND(100.0 * SUM(CASE
            WHEN days_for_shipping_real <= days_for_shipping_scheduled
             AND delivery_status <> 'Shipping canceled'
            THEN 1 ELSE 0 END) / COUNT(*), 2)                                 AS otif_rate_pct,

    -- Late delivery rate
    ROUND(100.0 * SUM(CASE WHEN delivery_status = 'Late delivery'
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                 AS late_delivery_rate_pct,

    -- Cancellation rate
    ROUND(100.0 * SUM(CASE WHEN delivery_status = 'Shipping canceled'
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                 AS cancellation_rate_pct,

    -- Transit time predictability
    ROUND(AVG(days_for_shipping_real - days_for_shipping_scheduled), 2)       AS avg_transit_variance_days,
    ROUND(STDDEV(days_for_shipping_real - days_for_shipping_scheduled), 2)    AS stddev_transit_variance,

    -- Financials
    ROUND(SUM(sales), 2)                                                      AS total_sales,
    ROUND(SUM(order_profit_per_order), 2)                                     AS total_profit,
    ROUND(100.0 * SUM(order_profit_per_order) / NULLIF(SUM(sales), 0), 2)     AS overall_margin_pct
FROM fact_orders;

-- ============================================================
-- 2. SHIPPING MODE SCORECARD
-- ============================================================
CREATE VIEW vw_shipping_mode_scorecard AS
SELECT
    sm.shipping_mode_name,
    COUNT(*)                                                                  AS volume,
    ROUND(100.0 * SUM(CASE
            WHEN f.days_for_shipping_real <= f.days_for_shipping_scheduled
            THEN 1 ELSE 0 END) / COUNT(*), 2)                                 AS on_time_pct,
    ROUND(AVG(f.days_for_shipping_real), 2)                                   AS avg_actual_days,
    ROUND(AVG(f.days_for_shipping_scheduled), 2)                              AS avg_scheduled_days,
    ROUND(AVG(f.days_for_shipping_real - f.days_for_shipping_scheduled), 2)   AS avg_delay_days,
    ROUND(100.0 * SUM(CASE WHEN f.delivery_status = 'Late delivery'
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                 AS late_pct,
    ROUND(SUM(f.order_profit_per_order), 2)                                   AS total_profit,
    ROUND(AVG(f.order_item_profit_ratio), 4)                                  AS avg_profit_ratio
FROM fact_orders f
JOIN dim_shipping_mode sm ON sm.shipping_mode_key = f.shipping_mode_key
GROUP BY sm.shipping_mode_name
ORDER BY volume DESC;

-- ============================================================
-- 3. MARKET PERFORMANCE
-- ============================================================
CREATE VIEW vw_market_performance AS
SELECT
    g.market,
    COUNT(*)                                                                  AS volume,
    ROUND(100.0 * SUM(CASE
            WHEN f.days_for_shipping_real <= f.days_for_shipping_scheduled
             AND f.delivery_status <> 'Shipping canceled'
            THEN 1 ELSE 0 END) / COUNT(*), 2)                                 AS otif_rate_pct,
    ROUND(AVG(f.days_for_shipping_real - f.days_for_shipping_scheduled), 2)   AS avg_delay_days,
    ROUND(SUM(f.sales), 2)                                                    AS total_sales,
    ROUND(SUM(f.order_profit_per_order), 2)                                   AS total_profit,
    ROUND(100.0 * SUM(f.order_profit_per_order) / NULLIF(SUM(f.sales), 0), 2) AS margin_pct
FROM fact_orders f
JOIN dim_geography g ON g.geography_key = f.order_geography_key
GROUP BY g.market
ORDER BY volume DESC;

-- ============================================================
-- 4. CATEGORY DEMAND TRENDS (monthly)
-- ============================================================
CREATE VIEW vw_category_demand_monthly AS
SELECT
    d.year,
    d.month_number,
    d.month_name,
    p.category_name,
    COUNT(*)                                                                  AS order_lines,
    SUM(f.order_item_quantity)                                                AS units_sold,
    ROUND(SUM(f.sales), 2)                                                    AS sales,
    ROUND(SUM(f.order_profit_per_order), 2)                                   AS profit
FROM fact_orders f
JOIN dim_date d    ON d.date_key    = f.order_date_key
JOIN dim_product p ON p.product_key = f.product_key
GROUP BY d.year, d.month_number, d.month_name, p.category_name
ORDER BY d.year, d.month_number, sales DESC;

-- ============================================================
-- 5. TOP 20 PROBLEM ROUTES
-- ============================================================
CREATE VIEW vw_top_problem_routes AS
SELECT
    og.market                                                                 AS origin_market,
    cg.country                                                                AS destination_country,
    COUNT(*)                                                                  AS shipment_count,
    ROUND(AVG(f.days_for_shipping_real - f.days_for_shipping_scheduled), 2)   AS avg_delay_days,
    ROUND(100.0 * SUM(CASE WHEN f.delivery_status = 'Late delivery'
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                 AS late_pct
FROM fact_orders f
JOIN dim_geography og ON og.geography_key = f.order_geography_key
JOIN dim_geography cg ON cg.geography_key = f.customer_geography_key
GROUP BY og.market, cg.country
HAVING COUNT(*) >= 50
ORDER BY avg_delay_days DESC
LIMIT 20;

-- ============================================================
-- 6. CUSTOMER SEGMENT PROFITABILITY
-- ============================================================
CREATE VIEW vw_customer_segment_profitability AS
SELECT
    c.customer_segment,
    COUNT(DISTINCT f.order_id)                                                AS unique_orders,
    COUNT(DISTINCT c.customer_id)                                             AS unique_customers,
    ROUND(SUM(f.sales), 2)                                                    AS total_sales,
    ROUND(SUM(f.order_profit_per_order), 2)                                   AS total_profit,
    ROUND(100.0 * SUM(f.order_profit_per_order) / NULLIF(SUM(f.sales), 0), 2) AS margin_pct,
    ROUND(SUM(f.sales) / NULLIF(COUNT(DISTINCT c.customer_id), 0), 2)         AS avg_sales_per_customer,
    ROUND(100.0 * SUM(CASE WHEN f.delivery_status = 'Late delivery'
                            THEN 1 ELSE 0 END) / COUNT(*), 2)                 AS late_pct
FROM fact_orders f
JOIN dim_customer c ON c.customer_key = f.customer_key
GROUP BY c.customer_segment
ORDER BY total_profit DESC;

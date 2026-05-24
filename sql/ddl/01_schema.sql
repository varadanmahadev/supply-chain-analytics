-- ============================================================
-- Supply Chain Analytics: Star Schema (MySQL 8.0)
-- Grain: one row per order line in fact_orders
-- Run this in MySQL Workbench against the `supply_chain` database
-- ============================================================

USE supply_chain;

-- Drop in reverse FK order
DROP TABLE IF EXISTS fact_orders;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_geography;
DROP TABLE IF EXISTS dim_shipping_mode;

-- ============================================================
-- DIMENSIONS
-- ============================================================

-- Date dimension (conformed across all facts)
CREATE TABLE dim_date (
    date_key            INT PRIMARY KEY,                  -- YYYYMMDD
    full_date           DATE NOT NULL,
    day_of_month        SMALLINT,
    day_of_week         SMALLINT,                         -- 1=Mon..7=Sun
    day_name            VARCHAR(10),
    week_of_year        SMALLINT,
    month_number        SMALLINT,
    month_name          VARCHAR(10),
    quarter             SMALLINT,
    year                SMALLINT,
    is_weekend          TINYINT(1)
) ENGINE=InnoDB COMMENT='Conformed date dimension. Covers order date and shipping date.';

-- Customer dimension (SCD Type 1)
CREATE TABLE dim_customer (
    customer_key        INT AUTO_INCREMENT PRIMARY KEY,
    customer_id         INT NOT NULL UNIQUE,              -- natural key from source
    customer_segment    VARCHAR(50),
    customer_city       VARCHAR(100),
    customer_state      VARCHAR(50),
    customer_country    VARCHAR(50),
    customer_zipcode    VARCHAR(20)
) ENGINE=InnoDB;

-- Product dimension with category + department hierarchy
CREATE TABLE dim_product (
    product_key             INT AUTO_INCREMENT PRIMARY KEY,
    product_card_id         INT NOT NULL UNIQUE,
    product_name            VARCHAR(255),
    product_price           DECIMAL(10,2),
    product_status          SMALLINT,
    category_id             INT,
    category_name           VARCHAR(100),
    department_id           INT,
    department_name         VARCHAR(100)
) ENGINE=InnoDB;

-- Geography (used for both order origin and customer location)
CREATE TABLE dim_geography (
    geography_key       INT AUTO_INCREMENT PRIMARY KEY,
    city                VARCHAR(100),
    state               VARCHAR(100),
    country             VARCHAR(100),
    market              VARCHAR(50),
    region              VARCHAR(100),
    latitude            DECIMAL(10,6),
    longitude           DECIMAL(10,6),
    UNIQUE KEY uq_geo (city, state, country, market)
) ENGINE=InnoDB COMMENT='Used as both order origin and customer location.';

-- Shipping mode (small static dim)
CREATE TABLE dim_shipping_mode (
    shipping_mode_key   INT AUTO_INCREMENT PRIMARY KEY,
    shipping_mode_name  VARCHAR(50) NOT NULL UNIQUE
) ENGINE=InnoDB;

-- ============================================================
-- FACT
-- ============================================================
CREATE TABLE fact_orders (
    order_item_id               INT PRIMARY KEY,        -- natural key
    order_id                    INT NOT NULL,

    -- FK to dimensions
    order_date_key              INT,
    shipping_date_key           INT,
    customer_key                INT,
    product_key                 INT,
    order_geography_key         INT,
    customer_geography_key      INT,
    shipping_mode_key           INT,

    -- Degenerate dimensions
    order_status                VARCHAR(50),
    delivery_status             VARCHAR(50),
    payment_type                VARCHAR(50),

    -- Measures: timing
    days_for_shipping_real      SMALLINT,
    days_for_shipping_scheduled SMALLINT,
    late_delivery_risk          TINYINT,

    -- Measures: financial
    order_item_quantity         SMALLINT,
    order_item_product_price    DECIMAL(10,2),
    order_item_discount         DECIMAL(10,2),
    order_item_discount_rate    DECIMAL(6,4),
    order_item_total            DECIMAL(12,2),
    sales                       DECIMAL(12,2),
    order_profit_per_order      DECIMAL(12,2),
    order_item_profit_ratio     DECIMAL(6,4),
    benefit_per_order           DECIMAL(12,2),
    sales_per_customer          DECIMAL(12,2),

    CONSTRAINT fk_fact_order_date    FOREIGN KEY (order_date_key)         REFERENCES dim_date(date_key),
    CONSTRAINT fk_fact_ship_date     FOREIGN KEY (shipping_date_key)      REFERENCES dim_date(date_key),
    CONSTRAINT fk_fact_customer      FOREIGN KEY (customer_key)           REFERENCES dim_customer(customer_key),
    CONSTRAINT fk_fact_product       FOREIGN KEY (product_key)            REFERENCES dim_product(product_key),
    CONSTRAINT fk_fact_order_geo     FOREIGN KEY (order_geography_key)    REFERENCES dim_geography(geography_key),
    CONSTRAINT fk_fact_cust_geo      FOREIGN KEY (customer_geography_key) REFERENCES dim_geography(geography_key),
    CONSTRAINT fk_fact_ship_mode     FOREIGN KEY (shipping_mode_key)      REFERENCES dim_shipping_mode(shipping_mode_key)
) ENGINE=InnoDB COMMENT='Grain: one row per order line item. Shipment performance + financial measures.';

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_fact_order_date      ON fact_orders(order_date_key);
CREATE INDEX idx_fact_shipping_date   ON fact_orders(shipping_date_key);
CREATE INDEX idx_fact_customer        ON fact_orders(customer_key);
CREATE INDEX idx_fact_product         ON fact_orders(product_key);
CREATE INDEX idx_fact_shipping_mode   ON fact_orders(shipping_mode_key);
CREATE INDEX idx_fact_order_geo       ON fact_orders(order_geography_key);
CREATE INDEX idx_fact_delivery_status ON fact_orders(delivery_status);

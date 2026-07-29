\set ON_ERROR_STOP on

CREATE SCHEMA commerce;

CREATE TABLE commerce.customers (
    customer_id bigint PRIMARY KEY,
    customer_name text NOT NULL,
    email_address text NOT NULL UNIQUE,
    phone_number text,
    region_code char(2) NOT NULL,
    loyalty_tier text NOT NULL CHECK (loyalty_tier IN ('bronze', 'silver', 'gold')),
    created_at timestamptz NOT NULL
);

CREATE TABLE commerce.products (
    product_id bigint PRIMARY KEY,
    sku varchar(24) NOT NULL UNIQUE,
    product_name text NOT NULL,
    category text NOT NULL,
    unit_price numeric(10, 2) NOT NULL CHECK (unit_price >= 0),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE commerce.orders (
    order_id bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES commerce.customers(customer_id),
    order_status text NOT NULL CHECK (order_status IN ('pending', 'processing', 'shipped', 'completed', 'cancelled')),
    ordered_at timestamptz NOT NULL,
    shipped_at timestamptz,
    total_amount numeric(12, 2) NOT NULL CHECK (total_amount >= 0),
    internal_note text
);

CREATE TABLE commerce.order_items (
    order_id bigint NOT NULL REFERENCES commerce.orders(order_id),
    line_number smallint NOT NULL,
    product_id bigint NOT NULL REFERENCES commerce.products(product_id),
    quantity integer NOT NULL CHECK (quantity > 0),
    unit_price numeric(10, 2) NOT NULL CHECK (unit_price >= 0),
    discount_percent numeric(5, 2) NOT NULL DEFAULT 0 CHECK (discount_percent BETWEEN 0 AND 100),
    PRIMARY KEY (order_id, line_number)
);

CREATE INDEX customers_region_tier_idx ON commerce.customers (region_code, loyalty_tier);
CREATE INDEX orders_customer_date_idx ON commerce.orders (customer_id, ordered_at DESC);
CREATE INDEX orders_status_idx ON commerce.orders (order_status);
CREATE INDEX products_active_category_idx ON commerce.products (category) WHERE active;

INSERT INTO commerce.customers VALUES
    (1, 'Amina Khan', 'amina@example.test', '+92-555-0101', 'PK', 'gold', '2026-01-04T09:00:00Z'),
    (2, 'Daniel Brooks', 'daniel@example.test', '+1-555-0102', 'US', 'silver', '2026-01-18T11:00:00Z'),
    (3, 'Noor Rahman', 'noor@example.test', '+971-555-0103', 'AE', 'gold', '2026-02-02T08:30:00Z'),
    (4, 'Sofia Chen', 'sofia@example.test', '+65-555-0104', 'SG', 'bronze', '2026-02-12T14:00:00Z'),
    (5, 'Mateo Silva', 'mateo@example.test', '+55-555-0105', 'BR', 'silver', '2026-03-01T16:00:00Z');

INSERT INTO commerce.products VALUES
    (10, 'AERO-STAND', 'Aero Desk Stand', 'Office', 89.00, true),
    (11, 'QUIET-HEADSET', 'QuietWave Headset', 'Electronics', 249.00, true),
    (12, 'LINK-DOCK', 'LinkPro USB-C Dock', 'Electronics', 179.00, true),
    (13, 'ERGO-KEYS', 'ErgoKeys Keyboard', 'Office', 129.00, true),
    (14, 'CLEAR-CAM', 'ClearView Camera', 'Electronics', 99.00, true);

INSERT INTO commerce.orders VALUES
    (1001, 1, 'completed', '2026-06-03T09:15:00Z', '2026-06-04T12:00:00Z', 308.00, NULL),
    (1002, 2, 'shipped', '2026-06-10T10:00:00Z', '2026-06-11T15:30:00Z', 447.00, NULL),
    (1003, 1, 'pending', '2026-06-15T13:20:00Z', NULL, 178.00, 'Fictional customer requested delayed delivery'),
    (1004, 3, 'completed', '2026-06-18T07:45:00Z', '2026-06-19T09:00:00Z', 607.00, NULL),
    (1005, 4, 'cancelled', '2026-06-20T11:10:00Z', NULL, 129.00, 'Fictional duplicate order'),
    (1006, 5, 'completed', '2026-06-22T16:40:00Z', '2026-06-23T10:30:00Z', 356.30, NULL),
    (1007, 2, 'processing', '2026-06-25T08:25:00Z', NULL, 278.00, NULL),
    (1008, 3, 'completed', '2026-06-27T12:00:00Z', '2026-06-28T14:10:00Z', 473.10, NULL);

INSERT INTO commerce.order_items VALUES
    (1001, 1, 12, 1, 179.00, 0),
    (1001, 2, 13, 1, 129.00, 0),
    (1002, 1, 11, 1, 249.00, 0),
    (1002, 2, 14, 2, 99.00, 0),
    (1003, 1, 10, 2, 89.00, 0),
    (1004, 1, 12, 2, 179.00, 0),
    (1004, 2, 11, 1, 249.00, 0),
    (1005, 1, 13, 1, 129.00, 0),
    (1006, 1, 14, 3, 99.00, 10),
    (1006, 2, 10, 1, 89.00, 0),
    (1007, 1, 12, 1, 179.00, 0),
    (1007, 2, 14, 1, 99.00, 0),
    (1008, 1, 11, 2, 249.00, 5);

CREATE ROLE connector_reader LOGIN PASSWORD 'connector-demo-readonly';
ALTER ROLE connector_reader SET default_transaction_read_only = on;

REVOKE CONNECT, TEMPORARY ON DATABASE connector_demo FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE connector_demo TO connector_reader;
GRANT USAGE ON SCHEMA commerce TO connector_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA commerce TO connector_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA commerce GRANT SELECT ON TABLES TO connector_reader;

ANALYZE commerce.customers;
ANALYZE commerce.products;
ANALYZE commerce.orders;
ANALYZE commerce.order_items;

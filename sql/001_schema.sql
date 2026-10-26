-- 001_schema.sql: DDL for the "Busy listing" lab (PostgreSQL 18).
-- pg_stat_statements is the evidence source; it needs shared_preload_libraries (set in docker-compose.yml).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  email        TEXT    NOT NULL,
  country_code CHAR(2) NOT NULL
);

CREATE TABLE orders (
  id          BIGSERIAL PRIMARY KEY,
  customer_id INTEGER       NOT NULL REFERENCES customers (id),
  status      TEXT          NOT NULL,
  total       NUMERIC(10,2) NOT NULL,
  created_at  TIMESTAMPTZ   NOT NULL,
  note        TEXT
);

COMMENT ON TABLE  orders            IS '1,000,000 orders; created_at has ties (three rows share each timestamp) so keyset paging needs id as a tie-breaker.';
COMMENT ON COLUMN orders.created_at IS 'Newest-first is the listing order; ties are broken by id.';

-- The ordering index a listing page would have from day one. The offset version already uses it, so the
-- cost measured for deep pages is the cost of discarding rows, not of sorting. Keyset paging seeks into it.
CREATE INDEX idx_orders_created_id ON orders (created_at DESC, id DESC);

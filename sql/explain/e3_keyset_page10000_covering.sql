-- Step 5, the same keyset page after migration 001 and 002: idx_orders_listing covers the five listed columns.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, total, created_at FROM orders WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765) ORDER BY created_at DESC, id DESC LIMIT 20;

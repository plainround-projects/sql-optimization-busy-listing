-- Step 4, page 1 by keyset: no bookmark yet, the first 20 rows of the index.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, total, created_at FROM orders ORDER BY created_at DESC, id DESC LIMIT 20;

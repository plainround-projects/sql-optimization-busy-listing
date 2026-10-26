-- Step 3, page 100 by offset: OFFSET 1980 produces 2,000 rows and keeps the last 20.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 1980;

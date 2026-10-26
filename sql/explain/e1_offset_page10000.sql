-- Step 3, page 10,000 by offset: OFFSET 199980 produces 200,000 rows and keeps the last 20.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 199980;

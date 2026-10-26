-- Step 3, page 1 by offset: OFFSET 0 reads 20 index entries.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 0;

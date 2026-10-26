-- Step 4, page 10,000 by keyset: seek straight past the bookmark (row 832765 is the last row of the page before).
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, total, created_at FROM orders WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765) ORDER BY created_at DESC, id DESC LIMIT 20;

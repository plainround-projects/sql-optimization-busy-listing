-- 003_queries.sql: the queries the lesson runs by hand. Plans for them are in explain/.
SET timezone = 'UTC';
\o /dev/null

-- Step 3, page 1 by offset (output discarded; timings are in explain/).
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 0;

-- Step 3, page 100 by offset.
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 1980;

-- Step 3, page 10,000 by offset: the database produces 200,000 rows and keeps the last 20.
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 199980;

-- Step 4, the same page "10,000" by keyset: rows strictly after the last row of the page before it.
SELECT id, customer_id, status, total, created_at FROM orders
WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765)
ORDER BY created_at DESC, id DESC LIMIT 20;

-- Step 2, the batched customer lookup that replaces 20 single lookups.
SELECT id, name FROM customers WHERE id = ANY (ARRAY[1, 2, 3, 4, 5]);
\o

-- Step 1, the two rankings the load will be judged by (empty until a load has run; make run fills them).
SELECT pg_stat_statements_reset() IS NOT NULL AS statistics_reset;

-- Step 1, top ten by total time: where the database spent its time.
SELECT left(query, 80) AS query, calls, round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 3) AS mean_ms
FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND query NOT ILIKE '%pg_stat_statements%' ORDER BY total_exec_time DESC LIMIT 10;

-- Step 1, top ten by calls: what the application asks for most often.
SELECT left(query, 80) AS query, calls, round(total_exec_time::numeric, 1) AS total_ms, round(mean_exec_time::numeric, 3) AS mean_ms
FROM pg_stat_statements WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND query NOT ILIKE '%pg_stat_statements%' ORDER BY calls DESC LIMIT 10;

-- Step 5, is the listing index covering and is the visibility map current? (relallvisible close to relpages)
SELECT relname, relpages, relallvisible FROM pg_class WHERE relname = 'orders';

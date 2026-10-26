-- 002_seed.sql: DML. 100,000 customers and 1,000,000 orders, then fresh statistics.
SELECT setseed(0.42);
SET timezone = 'UTC';

INSERT INTO customers (id, name, email, country_code)
SELECT n, 'Customer ' || n, 'customer' || n || '@example.test',
       (ARRAY['US','GB','DE','JP','IN','BR','FR','CA'])[1 + n % 8]
FROM generate_series(1, 100000) AS n;

-- created_at is shuffled against id, as after an import or a backfill, so the rows of one page are
-- spread over many heap pages. shuffled / 3 is integer division: three orders share each created_at.
INSERT INTO orders (customer_id, status, total, created_at, note)
SELECT 1 + floor(random() * 100000)::int,
       (ARRAY['pending','paid','shipped','failed'])[1 + floor(random() * 4)::int],
       round((random() * 500 + 5)::numeric, 2),
       timestamp '2026-01-01' + (numbered.shuffled / 3) * interval '40 seconds',
       'order note ' || numbered.n
FROM (SELECT n, row_number() OVER (ORDER BY random()) AS shuffled FROM generate_series(1, 1000000) AS n) AS numbered
ORDER BY numbered.n;

VACUUM (ANALYZE) customers;
VACUUM (ANALYZE) orders;

# SQL

## What it is

**SQL** (Structured Query Language) is the language for talking to relational databases. You describe *what* you want ("the ten newest orders of customer 7") and the database decides *how* to get it. An SQL text is made of **statements** ended by semicolons. Keywords are not case-sensitive (`select` and `SELECT` are the same); the convention is to write them in capitals.

## Why this repository uses it

SQL is the other half of the lab. The schema, the data (with a deliberate trap for pagination), the queries the ORM ends up sending, the index change and the plans are SQL files you can read and run by hand. The Python code mostly runs them, or generates the same statements through the ORM.

## Where it appears

| File | What it contains |
|---|---|
| `sql/001_schema.sql` | The extension, two tables, comments, and the original ordering index. |
| `sql/002_seed.sql` | The data generator: 100,000 customers, 1,000,000 orders. |
| `sql/003_queries.sql` | The queries the lesson runs by hand, and the two rankings. |
| `sql/reset.sql` | Drops the tables. |
| `sql/migrations/001`, `002` and `down/` | The index change (expand, then contract) and its undo. |
| `sql/explain/*.sql` | The `EXPLAIN` statements. |
| `src/busy_listing/infrastructure/sqlalchemy_orders.py` | The same queries built from Python (SQLAlchemy note). |

## How it works underneath

**Data definition (DDL):** statements that create or change structure.

- `CREATE TABLE name (column type constraints, ...)`: a new table. Constraints: `PRIMARY KEY` (unique, not null, indexed), `NOT NULL`.
- `CREATE INDEX name ON table (columns)`; `DROP INDEX name`; `DROP TABLE name`; `ALTER TABLE ...`.
- `COMMENT ON TABLE t IS 'text'` attaches a description stored in the database.
- `IF NOT EXISTS` / `IF EXISTS` make a statement do nothing instead of failing when the object already exists / is already gone. This makes scripts **idempotent**: safe to run twice.

**Queries and data changes (DML):**

- `SELECT columns FROM table WHERE condition GROUP BY columns ORDER BY column [DESC] LIMIT n`.
  - `WHERE` keeps rows for which the condition is true. `AND`, `OR`, `NOT`, `BETWEEN a AND b`, `=`, `<`, `>=`.
  - `GROUP BY` makes groups; aggregate functions summarise each group: `count(*)`, `max(x)`, `sum(x)`.
  - `ORDER BY` sorts (`DESC` is descending). `LIMIT n` keeps the first n rows.
  - `count(*) FILTER (WHERE condition)` counts only the rows meeting the condition.
  - `SELECT *` returns every column.
- `INSERT INTO table (columns) SELECT ... FROM generate_series(1, 1000000)`: inserts the rows a query produces. `generate_series(a, b)` produces the numbers a to b.
- `UPDATE`, `DELETE` change or remove rows.

**Expressions.** `x::int` converts the type (a **cast**). `CASE WHEN condition THEN a ELSE b END` chooses. `(ARRAY['a','b'])[2]` picks the second element of an array (counting starts at 1). `timestamp '2026-01-01' + n * interval '1 day'` adds a span of time. Text literals use single quotes; `''` inside means a quote. Double quotes name identifiers.

**Functions used here.** `random()` returns a decimal between 0 and 1; `floor(x)`; `round(x, 2)`; `repeat('ab', 3)` gives `ababab`; `md5(text)`; `string_agg(x, '')` joins text values; `date(timestamp)` extracts the date; `setseed(0.42)` makes `random()` repeatable.

**Transactions.** `BEGIN;` starts a group of statements, `COMMIT;` saves them all, `ROLLBACK;` throws them away.

**Maintenance and inspection statements.** `VACUUM`, `ANALYZE`, `EXPLAIN`, `SET timezone = 'UTC'` (change a session setting), `SHOW`.

**Comments.** `-- to end of line`. A statement ends at `;`.

**NULL** means "no value / unknown". `x = NULL` is never true; use `x IS NULL`. `NOT EXISTS (SELECT 1 FROM t)` is true when the table has no rows.

## Walkthrough of this repository's use

### `001_schema.sql`: structure

`sql/001_schema.sql`, lines 1 to 30:

```sql
-- 001_schema.sql: DDL for the "Busy listing" lab (PostgreSQL 18). Safe to run twice: IF NOT EXISTS throughout, one transaction.
-- pg_stat_statements is the evidence source; it needs shared_preload_libraries (set in docker-compose.yml).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

BEGIN;

CREATE TABLE IF NOT EXISTS customers (
  id           INTEGER PRIMARY KEY,
  name         TEXT    NOT NULL,
  email        TEXT    NOT NULL,
  country_code CHAR(2) NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
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
CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC);

COMMIT;
```

- Line 3: `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;` makes the statistics view available (pg_stat_statements note).
- `BEGIN;` (line 5) to `COMMIT;` (line 30): the tables and the index are created in one transaction.
- `customers`: `id INTEGER PRIMARY KEY`, `name TEXT NOT NULL`, `email TEXT NOT NULL`, `country_code CHAR(2) NOT NULL` (a text of exactly two characters).
- `orders`: `id BIGSERIAL PRIMARY KEY` (a 64-bit number filled from a sequence), `customer_id INTEGER NOT NULL REFERENCES customers (id)` (a **foreign key**: every order must name an existing customer), `status`, `total NUMERIC(10,2)` (an exact decimal), `created_at TIMESTAMPTZ NOT NULL`, `note TEXT` (may be empty).
- `COMMENT ON TABLE/COLUMN ... IS '...'` store descriptions in the database. The one on `orders` records the trap: three orders share each `created_at`, so paging by the time alone is wrong.
- Line 28: `CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC);` is the ordering index of the listing. The comment above it explains why it exists from the start: it makes the offset version's cost the cost of *discarding rows*, not of sorting.

### `002_seed.sql`: data

`sql/002_seed.sql`, lines 1 to 15:

```sql
-- 002_seed.sql: DML. 100,000 customers and 1,000,000 orders, then fresh statistics.
-- Safe to run twice: a table that already has rows is left alone (use `make reset` to start from nothing).
SELECT setseed(0.42);
SET timezone = 'UTC';

SELECT NOT EXISTS (SELECT 1 FROM customers) AS customers_empty, NOT EXISTS (SELECT 1 FROM orders) AS orders_empty \gset

\if :customers_empty
BEGIN;
INSERT INTO customers (id, name, email, country_code)
SELECT n, 'Customer ' || n, 'customer' || n || '@example.test',
       (ARRAY['US','GB','DE','JP','IN','BR','FR','CA'])[1 + n % 8]
FROM generate_series(1, 100000) AS n;
COMMIT;
\endif
```

- `SELECT setseed(0.42);` fixes the starting point of `random()`; `SET timezone = 'UTC';` fixes how timestamp literals are read.
- Line 6: one query computes two true/false values, `customers_empty` and `orders_empty`, each `NOT EXISTS (SELECT 1 FROM table)`. The closing `\gset` is a psql command that stores them in psql variables (psql note). `\if :customers_empty ... \endif` runs the block only if the variable is true, so a second `make db` loads nothing.
- The customers: `SELECT n, 'Customer ' || n, 'customer' || n || '@example.test', (ARRAY['US','GB','DE','JP','IN','BR','FR','CA'])[1 + n % 8] FROM generate_series(1, 100000) AS n;` produces one row per number `n` from 1 to 100,000. `||` joins text (the number `n` is converted). `n % 8` is the remainder of `n` divided by 8 (0 to 7), so `[1 + n % 8]` picks one of the eight country codes (array positions count from 1).

`sql/002_seed.sql`, lines 17 to 33:

```sql
-- created_at is shuffled against id, as after an import or a backfill, so the rows of one page are
-- spread over many heap pages. shuffled / 3 is integer division: three orders share each created_at.
\if :orders_empty
BEGIN;
INSERT INTO orders (customer_id, status, total, created_at, note)
SELECT 1 + floor(random() * 100000)::int,
       (ARRAY['pending','paid','shipped','failed'])[1 + floor(random() * 4)::int],
       round((random() * 500 + 5)::numeric, 2),
       timestamp '2026-01-01' + (numbered.shuffled / 3) * interval '40 seconds',
       'order note ' || numbered.n
FROM (SELECT n, row_number() OVER (ORDER BY random()) AS shuffled FROM generate_series(1, 1000000) AS n) AS numbered
ORDER BY numbered.n;
COMMIT;
\endif

VACUUM (ANALYZE) customers;
VACUUM (ANALYZE) orders;
```

- The comment says what the data is built to do: `created_at` is **shuffled** against `id`, as after an import, so that the rows of one page are spread over many table pages; and **three orders share each timestamp**.
- `INSERT INTO orders (...) SELECT ... FROM (SELECT n, row_number() OVER (ORDER BY random()) AS shuffled FROM generate_series(1, 1000000) AS n) AS numbered ORDER BY numbered.n;`. The inner query numbers the rows 1 to 1,000,000 as `n` and gives each a `shuffled` number: `row_number() OVER (ORDER BY random())` is a **window function** that assigns 1, 2, 3, ... in random order. The outer `SELECT` then uses `numbered.shuffled / 3` — **integer division**, because both are integers — so three consecutive shuffled numbers give the same result. `timestamp '2026-01-01' + (numbered.shuffled / 3) * interval '40 seconds'` turns that into a time 40 seconds apart per group. That is how three orders get the same `created_at` and ids are unrelated to the order of time.
- `1 + floor(random() * 100000)::int` picks a customer id from 1 to 100,000; the status is one of four values at random; `round((random() * 500 + 5)::numeric, 2)` is a price; `'order note ' || numbered.n` is a short note. `ORDER BY numbered.n` makes the table rows be inserted in id order.
- Lines 32 and 33: `VACUUM (ANALYZE) customers;` and `VACUUM (ANALYZE) orders;` collect statistics and set the visibility map (PostgreSQL note).

### `003_queries.sql`: the lesson's queries

`sql/003_queries.sql`, lines 1 to 37:

```sql
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
```

- Line 3: `\o /dev/null` (a psql command) sends output to nowhere; line 21 `\o` restores it. The wide results are not printed.
- Lines 6, 9, 12: page 1, page 100 and page 10,000 by offset: `LIMIT 20 OFFSET 0 / 1980 / 199980` (`OFFSET` skips that many rows first).
- Lines 15 to 17: the same position reached by keyset: `WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765)` is a **row comparison**: it compares the pair like a two-digit number, first the time, then the id for equal times. With `ORDER BY created_at DESC, id DESC LIMIT 20`.
- Line 20: `WHERE id = ANY (ARRAY[1, 2, 3, 4, 5])` finds the customers whose id is in the list: one query instead of one per order.
- Lines 24 to 34: reset the statistics, then the two rankings (pg_stat_statements note).
- Line 37: `SELECT relname, relpages, relallvisible FROM pg_class WHERE relname = 'orders';` shows how many table pages exist and how many are marked all-visible, which tells whether an index-only scan can avoid the table.

### `reset.sql` and the migrations

`sql/reset.sql`, lines 1 to 5:

```sql
-- reset.sql: drop everything the lab created, so 001 to 002 rebuild it from nothing. `make reset` runs this.
BEGIN;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
COMMIT;
```
`sql/migrations/001_expand_covering_listing_index.sql`, lines 1 to 9:

```sql
-- Step 5, expand: build the covering index next to the old one, so the listing never runs without an index.
-- INCLUDE keeps the listed columns in the leaf pages; the key stays (created_at DESC, id DESC).
-- In production on a live table this would be CREATE INDEX CONCURRENTLY (see project 3 of this track).
-- Safe to run twice. Undo: down/001_expand_covering_listing_index.down.sql.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_orders_listing ON orders (created_at DESC, id DESC) INCLUDE (customer_id, status, total);
COMMIT;
-- An index-only scan needs the visibility map to mark pages all-visible (VACUUM cannot run in a transaction).
VACUUM orders;
```
`sql/migrations/002_contract_drop_old_listing_index.sql`, lines 1 to 5:

```sql
-- Step 5, contract: the covering index has the same key, so the old narrow one only costs writes.
-- Safe to run twice. Undo: down/002_contract_drop_old_listing_index.down.sql.
BEGIN;
DROP INDEX IF EXISTS idx_orders_created_id;
COMMIT;
```

`reset.sql` drops both tables in one transaction (`CASCADE` also drops what depends on them). Migration `001` ("expand") creates the covering index next to the old one inside a transaction, then runs a plain `VACUUM orders` outside it. Migration `002` ("contract") drops the old narrow index. The PostgreSQL-indexes note explains why. The down scripts undo them: `down/002...` recreates the old index and `down/001...` drops the covering one; run them in that order so one ordering index always exists.

## Try it yourself

(After `make up db`; `P="docker compose exec -T db psql -U lab -d lab"`.)

1. `$P -c "select count(*), count(distinct created_at) from orders"` prints `1000000` and `333334`: 1,000,000 orders but only 333,334 different times, because three orders share each timestamp (all groups but the first and the last).
2. `$P -c "select id, created_at from orders order by created_at desc, id desc limit 6"` shows pairs of three rows with the same `created_at`.
3. `$P -c "select (array['a','b','c'])[2], 7::text || 'x', 10 % 8, 7 / 3, 7 / 3.0"` prints `b`, `7x`, `2`, `2`, `2.3333...`: integer division versus decimal division.
4. `$P -c "select c.name, count(*) from orders o join customers c on c.id = o.customer_id group by c.name order by 2 desc limit 3"` joins the two tables and counts orders per customer.
5. `make db` a second time finishes quickly and `$P -c "select count(*) from orders"` still says 1,000,000: the guarded seed did nothing.

## Mistakes people make

- `SELECT *` in application queries.
- Comparing with `= NULL`.
- Forgetting `WHERE` on `UPDATE` and `DELETE`.
- Wrapping an indexed column in a function in `WHERE`.
- Assuming rows come back in a fixed order without `ORDER BY`.
- Running a script twice and getting "already exists" errors (use `IF NOT EXISTS`).
- Time zone surprises with `timestamp` versus `timestamptz`.

**How this repository avoids them.** Every DDL has `IF [NOT] EXISTS`. The seed refuses to double-load. Time zone is fixed. The ordering always has a tie-breaker (`id`). The listing selects only the columns it shows. The migration is expand then contract, with down scripts.

## Check yourself

1. What do `WHERE` and `GROUP BY` each do? *`WHERE` filters rows; `GROUP BY` forms groups for aggregate functions.*
2. What does `IF NOT EXISTS` give a script? *Safe repetition: nothing happens, and no error, if the object exists.*
3. What does `x::int` do? *Converts the value `x` to the type integer.*
4. What happens to the statements between `BEGIN` and `ROLLBACK`? *Their effects are discarded.*
5. Why is `col = NULL` never true? *NULL means unknown, and comparing with unknown yields unknown; use `IS NULL`.*

## Further reading

- PostgreSQL 18, "SQL Commands": https://www.postgresql.org/docs/18/sql-commands.html and "The SQL Language": https://www.postgresql.org/docs/18/sql.html
- "Functions and Operators": https://www.postgresql.org/docs/18/functions.html

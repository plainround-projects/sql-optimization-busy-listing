# PostgreSQL

## What it is

**PostgreSQL** (often "Postgres") is a **database server**: a program that stores tables of data on disk and answers questions about them, written in a language called SQL. Many programs can connect to it at the same time over the network, and it keeps their changes consistent. It is free and open source. This repository uses major version **18**, run from the Docker image `postgres:18`.

## Why this repository uses it

The lesson is about what a real database does with an ORM's queries, so it needs a real one, with its own statistics (`pg_stat_statements`) and its own planner. PostgreSQL 18 is the engine the track assumes. The evidence of every claim in the README is PostgreSQL's own output: rankings of statements, plans, page counts.

## Where it appears

| File | What it does with PostgreSQL |
|---|---|
| `docker-compose.yml` | Starts `postgres:18` with `pg_stat_statements` preloaded. |
| `sql/001_schema.sql`, `002_seed.sql`, `003_queries.sql`, `reset.sql` | Create, fill, query and drop the lab's tables. |
| `sql/migrations/` and `sql/migrations/down/` | The index change and its undo. |
| `sql/explain/*.sql` and `*.txt` | The plans and their captured output. |
| `src/busy_listing/infrastructure/` | The Python side: SQLAlchemy, psycopg, statistics, index changes. |

## How it works underneath

**Server and processes.** One main process, the **postmaster**, listens on a network port (5432 by default). For every client connection it starts a separate **backend process**. Other background processes write dirty data to disk, write the log, and clean up (see below).

**Objects.** A server holds several **databases**; a database holds **schemas** (folders for names; `public` by default); a schema holds **tables**, **indexes**, **sequences**, **views** (saved queries) and **functions**. A **table** has **columns** (name and type) and **rows**. Common types: `integer`/`bigint` (whole numbers), `text`, `numeric(10,2)` (exact decimals), `timestamptz` (a moment in time with time zone), `boolean`. A **sequence** hands out increasing numbers; `BIGSERIAL` is a `bigint` column fed by a sequence. A **primary key** is a column (or set) whose values are unique; PostgreSQL builds an index for it automatically.

**Pages and the heap.** Table data lives in files on disk cut into **pages** of 8 kilobytes. A page holds several rows (**tuples**). The table's own file of pages, in no particular order, is called the **heap**. Reading a row means reading its page. A page read from disk is expensive; a page already in memory is cheap. PostgreSQL keeps recently used pages in **shared buffers** (a memory cache, set here to 512 MB), and the operating system keeps its own cache as well. A plan's `Buffers: shared hit=N read=M` counts pages found in the cache (`hit`) and pages fetched from outside it (`read`). **Pages touched** (hit + read) is a stable measure of work, while milliseconds depend on the machine.

**Transactions and MVCC.** A **transaction** is a group of statements that happen all together or not at all (`BEGIN ... COMMIT`, or `ROLLBACK` to undo). PostgreSQL uses **multi-version concurrency control (MVCC)**: an `UPDATE` or `DELETE` does not overwrite a row, it writes a new version and marks the old one as dead for later transactions. Readers never block writers. The price: dead row versions pile up.

**VACUUM.** `VACUUM` removes dead row versions so the space can be reused, and updates the **visibility map**, a small bitmap that records which pages hold only rows visible to everyone. `autovacuum` is a background process that does this automatically. `VACUUM (ANALYZE)` also refreshes statistics.

**WAL (write-ahead log).** Before any change reaches the table files, PostgreSQL writes a description of it to the **write-ahead log**. After a crash the server replays the log. Every inserted row writes a WAL record for the heap *and one for every index*, which is why indexes make writes more expensive.

**The planner and statistics.** For each statement the **planner** considers several ways to get the answer and picks the one with the lowest *estimated cost*, using **statistics** that `ANALYZE` collected: the number of rows, the most common values of each column, how many distinct values there are, and how closely the order of the values matches the order of the rows on disk (all visible in the `pg_stats` view). Wrong statistics lead to bad plans. `EXPLAIN` shows the chosen plan (see the EXPLAIN note).

**TOAST.** A row must fit in a page. A big value (more than about 2 kilobytes) is moved to a separate **TOAST table** ("The Oversized-Attribute Storage Technique") and the row keeps a pointer to it; it is also compressed unless told otherwise. Queries that do not select that column never touch the TOAST table. `ALTER TABLE ... ALTER COLUMN ... SET STORAGE EXTERNAL` stores the value out of line without compression.

**Catalogs and statistics views.** PostgreSQL describes itself in tables and views you can query: `pg_stat_user_tables` (rows, last analyze), `pg_stat_user_indexes` (how often each index was used), `pg_stats` (column statistics), `pg_class` (sizes in pages), `pg_locks`, `pg_stat_activity`. `pg_relation_size(oid)` gives bytes; `pg_size_pretty(n)` formats them.

**Settings.** Server settings (`shared_buffers`, `max_parallel_workers_per_gather`...) are set at start with `postgres -c name=value`, in a config file, or per session with `SET name = value`. `SHOW name` reads one.

## Walkthrough of this repository's use

### The server and its settings

`docker-compose.yml`, lines 13 to 25:

```yaml
    command:
      - postgres
      - -c
      - shared_preload_libraries=pg_stat_statements
      - -c
      - pg_stat_statements.track_utility=off
      - -c
      - pg_stat_statements.max=5000
      - -c
      - max_parallel_workers_per_gather=0
      - -c
      - shared_buffers=512MB
    shm_size: 1gb
```

- `shared_preload_libraries=pg_stat_statements`, `pg_stat_statements.track_utility=off`, `pg_stat_statements.max=5000`: the statistics extension (pg_stat_statements note).
- `max_parallel_workers_per_gather=0`: PostgreSQL can split one big scan between helper processes. That makes plans longer to read and timings less repeatable, so the lab switches it off, both for the whole server and again per connection (psycopg note).
- `shared_buffers=512MB`: the cache of table and index pages (8 kB each), about 65,000 pages. The `orders` table is about 87 MB (11,069 pages; the last query of `sql/003_queries.sql` shows `relpages`), so it fits comfortably: after one pass nearly every plan reports only `hit=` pages, as `sql/explain/*.txt` show. That is deliberate: the lesson compares the *work* a query does (pages touched), not the speed of a disk.
- The data lives in the volume `pgdata`; the image creates the user and database from the `POSTGRES_*` variables on first start only.

### Foreign keys and the tables

`sql/001_schema.sql`, lines 7 to 21:

```sql
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
```

`customers` has 100,000 rows and `orders` 1,000,000. `customer_id INTEGER NOT NULL REFERENCES customers (id)` is a **foreign key**: PostgreSQL refuses an order for a customer that does not exist, and the relationship is what the ORM's `Order.customer` follows. Note that PostgreSQL does not create an index on a foreign-key column by itself; the lesson never looks up orders by customer, only customers by id (which is the primary key).

### Rows, pages and the cost of an offset

An order row is about 49 bytes wide (`width=49` in the plans), so a page holds roughly 90 rows and the table is about 11,000 pages. Look at the three offset plans:

`sql/explain/e1_offset_page1.txt`, lines 1 to 3:

```text
Limit  (cost=0.42..1.92 rows=20 width=49) (actual time=0.009..0.031 rows=20.00 loops=1)
  Buffers: shared hit=23
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.009..0.029 rows=20.00 loops=1)
```
`sql/explain/e1_offset_page100.txt`, lines 1 to 3:

```text
Limit  (cost=148.31..149.80 rows=20 width=49) (actual time=1.099..1.107 rows=20.00 loops=1)
  Buffers: shared hit=2010
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.010..1.045 rows=2000.00 loops=1)
```
`sql/explain/e1_offset_page10000.txt`, lines 1 to 3:

```text
Limit  (cost=14936.53..14938.02 rows=20 width=49) (actual time=188.438..188.463 rows=20.00 loops=1)
  Buffers: shared hit=200751
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.027..181.132 rows=200000.00 loops=1)
```

Each shows `Buffers: shared hit=N` for the top node: 23 pages for page 1, 2,010 for page 100, 200,751 for page 10,000. `OFFSET 199980` cannot jump: PostgreSQL walks the index in order, produces 200,000 rows (`rows=200000.00` in the `Index Scan` line), fetches each row from the table to give it to the `Limit` node, and throws the first 199,980 away. Because `created_at` was shuffled against `id` when the table was loaded, consecutive rows in the index live on different table pages, so 200,000 rows cost about 200,751 page touches: roughly one page per row. In a table where time and id are perfectly correlated, the same offset would touch far fewer pages (the README measures 2,986).

### Ties, and why the cursor has two columns

The seed gives three orders the same `created_at`. `ORDER BY created_at DESC, id DESC` makes the order total (no two rows compare equal). A keyset cursor on `created_at` alone would skip rows that tie across a page boundary; the pair `(created_at, id)` never does. The integration tests prove both (`test_common_mistake_a_cursor_on_created_at_alone_skips_tied_orders`).

### MVCC and the walk test

PostgreSQL's multi-version concurrency control lets one connection insert rows while another reads without blocking. The test `test_step4_every_order_exactly_once_while_new_orders_are_inserted` pages through all 1,000,000 orders in pages of 1,000 while a second connection inserts new orders (some dated in the future, some with duplicate timestamps) and checks that every existing order appears exactly once. An offset walk would repeat or skip rows when rows arrive at the front (`test_common_mistake_offset_paging_repeats_a_row_...`); a keyset walk does not.

### Vacuum and the visibility map

`sql/002_seed.sql`, lines 32 to 33:

```sql
VACUUM (ANALYZE) customers;
VACUUM (ANALYZE) orders;
```
`sql/migrations/001_expand_covering_listing_index.sql`, lines 8 to 9:

```sql
-- An index-only scan needs the visibility map to mark pages all-visible (VACUUM cannot run in a transaction).
VACUUM orders;
```

After the data load, `VACUUM (ANALYZE)` collects statistics and marks pages in the visibility map. An **index-only scan** can skip a table page only if the visibility map says all its rows are visible to everyone; otherwise it must check the table (a `Heap Fetch`). Migration `001` runs a plain `VACUUM orders` *outside* its transaction (PostgreSQL does not allow `VACUUM` inside one) so that `e3_keyset_page10000_covering.txt` shows `Heap Fetches: 0`. `sql/003_queries.sql` ends with a query on `pg_class` (`relpages`, `relallvisible`) to check that the two are close.

### Statistics views used

`pg_stat_statements` (the lesson), `pg_database` (the database's `oid`, to filter the view), `pg_extension` (is the extension installed? used by the health check), `pg_class` (pages of a table), `to_regclass('public.orders')` (does the table exist?).

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -c "show shared_buffers" -c "show shared_preload_libraries" -c "show max_parallel_workers_per_gather"` — prints `512MB`, `pg_stat_statements`, `0`.
2. `docker compose exec db psql -U lab -d lab -c "select relname, relpages, relallvisible, reltuples::bigint from pg_class where relname in ('orders','customers')"` — about 11,000 pages for `orders`, and `relallvisible` close to `relpages`.
3. `docker compose exec db psql -U lab -d lab -c "select pg_size_pretty(pg_relation_size('orders')), pg_size_pretty(pg_relation_size('idx_orders_created_id'))"` — the size of the table (about 87 MB) and of its ordering index.
4. `docker compose exec db psql -U lab -d lab -c "\d+ orders"` — the columns, the foreign key, the index and the table comment.
5. `docker compose exec db psql -U lab -d lab -c "select a.id, a.created_at from orders a join orders b on a.created_at = b.created_at and a.id < b.id limit 3"` — shows orders sharing a timestamp.

## Mistakes people make

- Assuming an index is always used (the planner may prefer a table scan, rightly or not).
- Judging a query by one timing without noticing that the cache was cold or warm.
- Forgetting `ANALYZE` after loading lots of data, so the planner works with stale statistics.
- Leaving transactions open, which stops `VACUUM` from cleaning.
- Using `SELECT *` on tables with big columns.
- Running a destructive command on the wrong database.

**How this repository avoids them.** Pages are counted, not just milliseconds; every offset has a keyset counterpart; a tie-breaker column makes the order total; `VACUUM` runs after the load and after the index change; and migrations are transactional, idempotent and have down scripts.

## Check yourself

1. What is a page, and how big is it? *The unit in which PostgreSQL stores and reads table data: 8 kilobytes holding several rows.*
2. What does MVCC do on `UPDATE`? *It writes a new version of the row and marks the old one dead; readers keep seeing the version that fits their snapshot.*
3. What does `VACUUM` do? *Removes dead row versions so space is reused and updates the visibility map.*
4. Why do indexes make inserts slower? *Each insert must also add an entry to every index, and each of those writes a WAL record.*
5. What is TOAST? *Out-of-line storage of large values in a separate table, so ordinary rows stay small.*

## Further reading

- PostgreSQL 18 documentation: https://www.postgresql.org/docs/18/ — "Database Physical Storage" (https://www.postgresql.org/docs/18/storage.html), "Concurrency Control" (https://www.postgresql.org/docs/18/mvcc.html), "Routine Vacuuming" (https://www.postgresql.org/docs/18/routine-vacuuming.html), "Write-Ahead Logging" (https://www.postgresql.org/docs/18/wal-intro.html), "Planner statistics" (https://www.postgresql.org/docs/18/planner-stats.html).

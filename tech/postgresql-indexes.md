# PostgreSQL indexes

## What it is

An **index** is a second structure kept beside a table that lets the database find rows without reading the whole table, like the index at the back of a book. Without one, finding the rows with `customer_id = 7` means reading every page of the table (a **sequential scan**). With one, the database looks up `7` in a small sorted structure and goes straight to the matching rows.

## Why this repository uses it

Deep pages are slow because of what an index cannot do (jump to the 200,000th row), and fast again when the query is rewritten to use the index the way it works (seek to a position). The last step adds a covering index and drops the old one. Both the original ordering index and the covering index are `(created_at DESC, id DESC)`.

## Where it appears

| File | Index |
|---|---|
| `sql/001_schema.sql` | `orders_pkey (id)` and `idx_orders_created_id (created_at DESC, id DESC)`. |
| `sql/migrations/001_expand_covering_listing_index.sql` | `idx_orders_listing (created_at DESC, id DESC) INCLUDE (customer_id, status, total)`. |
| `sql/migrations/002_contract_drop_old_listing_index.sql` | Drops `idx_orders_created_id`. |
| `src/busy_listing/infrastructure/lab_indexes.py` | Moves the table between the two states. |
| `sql/explain/e1_*.txt`, `e2_*.txt`, `e3_*.txt` | The plans that show each index at work. |

## How it works underneath

**B-tree.** The default index type is a **B-tree**: a balanced tree of 8 kB pages. The top page lists ranges of key values and points to pages below; the bottom pages (**leaf pages**) hold the keys in sorted order, each with a pointer (the row's physical address) to the row in the table. Finding one key takes only a handful of page reads, even for a million rows, because the tree is shallow. Because the leaves are sorted, a B-tree also answers range questions (`created_at >= x AND created_at < y`) by finding the start and reading forward, and it can return rows already in sorted order (so no separate sort step is needed).

**Multi-column indexes.** `(customer_id, created_at DESC)` sorts by `customer_id` first, and rows with the same customer by `created_at` newest first. All the rows of one customer therefore sit together, newest first. The index helps queries that fix the first column (equality) and then use the next (a range or an order). It does *not* help a query that only mentions `created_at`. The column order matters: equality columns first, then the range or sort column.

**Direction.** `DESC` stores that column in descending order, so "newest first" can be read from the start.

**Covering index (`INCLUDE`).** `CREATE INDEX ... (a, b) INCLUDE (c, d)` also stores `c` and `d` in the leaf pages, though they are not part of the sort key. A query that needs only `a, b, c, d` can be answered from the index alone: an **index-only scan**, which never visits the table. The catch: the index entry does not say whether the row is *visible* to the current transaction, so PostgreSQL consults the **visibility map**; if the page is marked all-visible it trusts the index, otherwise it visits the table page (a *heap fetch*). `VACUUM` keeps the visibility map current.

**Scan types you will see in plans.**

- `Seq Scan`: read the whole table.
- `Index Scan`: walk the index and fetch each matching row from the table in index order.
- `Index Only Scan`: answer from the index alone.
- `Bitmap Index Scan` + `Bitmap Heap Scan`: collect all matching row addresses from the index into a bitmap, sort them by page, then read each table page once. Used when many rows match.

**Why a function on the column blocks the index.** An index on `created_at` is sorted by `created_at`, not by `date(created_at)`. The condition `date(created_at) = '2026-03-14'` forces the database to compute the function for every row. Rewrite it as a range on the bare column: `created_at >= '2026-03-14' AND created_at < '2026-03-15'`. Conditions that an index can use are called **sargable** (search-argument-able).

**Costs.** An index takes disk space and slows every `INSERT`, `UPDATE` and `DELETE` (each change must update every index, and writes WAL for it). Add an index when a read is worth that cost; drop one that another index makes redundant: `(customer_id, created_at) INCLUDE (...)` has the same leading columns as `(customer_id, created_at)`, so it serves the same lookups.

**`CREATE INDEX IF NOT EXISTS`** makes creation safe to repeat. A plain `CREATE INDEX` blocks writes to the table while it builds; `CREATE INDEX CONCURRENTLY` does not (but cannot run inside a transaction and takes longer).

## Walkthrough of this repository's use

### The ordering index and offset paging

`sql/001_schema.sql`, lines 26 to 28:

```sql
-- The ordering index a listing page would have from day one. The offset version already uses it, so the
-- cost measured for deep pages is the cost of discarding rows, not of sorting. Keyset paging seeks into it.
CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC);
```

The index is sorted newest first, ties broken by the larger id first, which is exactly the order of the listing, so `ORDER BY created_at DESC, id DESC LIMIT 20` needs no sort: PostgreSQL reads the first 20 entries of the index. For page 1 that is 23 pages (`e1_offset_page1.txt`: `Index Scan using idx_orders_created_id`, `Buffers: shared hit=23`). For `OFFSET 199980` the same index scan has to produce 200,000 entries and fetch each row from the table: 200,751 pages (`e1_offset_page10000.txt`, `rows=200000.00`). The index cannot count; it can only be walked.

### Keyset paging: seek, don't skip

`sql/explain/e2_keyset_page10000.sql`, lines 1 to 4:

```sql
-- Step 4, page 10,000 by keyset: seek straight past the bookmark (row 832765 is the last row of the page before).
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, customer_id, status, total, created_at FROM orders WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765) ORDER BY created_at DESC, id DESC LIMIT 20;
```
`sql/explain/e2_keyset_page10000.txt`, lines 1 to 6:

```text
Limit  (cost=0.42..2.19 rows=20 width=32) (actual time=0.007..0.016 rows=20.00 loops=1)
  Buffers: shared hit=23
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..70530.77 rows=797620 width=32) (actual time=0.007..0.014 rows=20.00 loops=1)
        Index Cond: (ROW(created_at, id) < ROW('2026-05-04 11:02:00+00'::timestamp with time zone, 832765))
        Index Searches: 1
        Buffers: shared hit=23
```

`WHERE (created_at, id) < ('2026-05-04 11:02:00+00', 832765)` compares the pair as a **row**: the pair is smaller when the time is smaller, or the time is equal and the id is smaller. Because the index is sorted by exactly that pair, PostgreSQL can find the starting position directly (`Index Cond: (ROW(created_at, id) < ROW(...))` in the plan, `Index Searches: 1`) and then read 20 entries: 23 pages, the same as page 1, wherever the position is. That is what the test `test_step4_a_deep_keyset_page_costs_about_what_page_one_costs` asserts.

Why two columns: three orders have each timestamp. If the cursor were only the time, "rows older than `t`" would skip the other rows with time `t` that had not yet been sent, or repeat some. With the id as tie-breaker every row has one exact position.

### The covering index: expand, then contract

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

`INCLUDE (customer_id, status, total)` stores those three columns in the index's leaf pages. The listing needs `id, customer_id, status, total, created_at`: the key supplies `created_at` and `id`, the included columns supply the rest, so the whole answer can come from the index without touching the table. The plan shows it: `Index Only Scan using idx_orders_listing`, `Heap Fetches: 0`, `Buffers: shared hit=5` against 23 (`e3_keyset_page10000_covering.txt`). The `VACUUM orders` at the end refreshes the visibility map that makes `Heap Fetches: 0` possible.

**Expand then contract** is the safe way to change an index on a table in use. *Expand*: build the new index next to the old one (the listing never runs without an index). Check that it works. *Contract*: drop the old one.

`sql/migrations/002_contract_drop_old_listing_index.sql`, lines 1 to 5:

```sql
-- Step 5, contract: the covering index has the same key, so the old narrow one only costs writes.
-- Safe to run twice. Undo: down/002_contract_drop_old_listing_index.down.sql.
BEGIN;
DROP INDEX IF EXISTS idx_orders_created_id;
COMMIT;
```

The old `(created_at DESC, id DESC)` index has the same key as the new one, so it only costs writes. The comment on migration `001` says the production form would be `CREATE INDEX CONCURRENTLY`, which does not block writers (the next project of the track). The down scripts bring each state back; they must be run in the order `down/002` then `down/001`, so that one ordering index always exists.

### How the replay uses them

`src/busy_listing/infrastructure/lab_indexes.py`, lines 29 to 37:

```python
    def reset_to(self, step: int) -> None:
        """Rebuild the original ordering index, then apply migrations 1 to `step`; refresh statistics."""
        with session(self._settings) as connection:
            for name in LESSON_INDEXES:
                connection.execute(f"DROP INDEX IF EXISTS {name}")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC)")
            for path in self.migrations()[:step]:
                run_file(connection, path)
            connection.execute("VACUUM ANALYZE orders")
```

`reset_to(0)` = the original index only (phases 1 to 3); `reset_to(2)` = migrations 1 and 2 applied = the covering index only (phase 4). Whatever state the table was in, `reset_to` first drops both lesson indexes, recreates the original, then applies the migrations asked for.

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -c "\d orders"` — lists `orders_pkey` and `idx_orders_created_id` with their definitions.
2. `docker compose exec db psql -U lab -d lab -c "explain (analyze, buffers) select * from orders order by created_at desc, id desc limit 20 offset 199980"` — an `Index Scan` that produces 200,000 rows; `Buffers` shows about 200,000 pages.
3. `docker compose exec -T db psql -U lab -d lab < sql/migrations/001_expand_covering_listing_index.sql`, then `docker compose exec db psql -U lab -d lab -c "\di+ idx_orders_listing"` — the new index and its size.
4. Run `explain (analyze, buffers) select id, customer_id, status, total, created_at from orders where (created_at, id) < ('2026-05-04 11:02:00+00', 832765) order by created_at desc, id desc limit 20` (as in `sql/explain/e3_keyset_page10000_covering.sql`): an `Index Only Scan using idx_orders_listing` with `Heap Fetches: 0`.
5. Undo with `docker compose exec -T db psql -U lab -d lab < sql/migrations/down/001_expand_covering_listing_index.down.sql` (the original index still exists, so nothing is lost).

## Mistakes people make

- Indexing every column "just in case".
- Putting a range column before an equality column in a multi-column index.
- Wrapping the indexed column in a function in the `WHERE` clause.
- Forgetting that an index must be maintained on every write.
- Expecting an index-only scan on a table that was never vacuumed.
- Keeping two indexes where one covers both.

**How this repository avoids them.** Every ordering has a tie-breaker. The listing selects only indexed columns. The index change is expand, verify, contract, each as an idempotent transaction with a down script, and the visibility map is refreshed after the expand step.

## Check yourself

1. Why is a B-tree lookup fast even for a million rows? *The tree is shallow, so only a few pages are read to find one key.*
2. Why does `date(created_at) = '2026-03-14'` not use an index on `created_at`? *The index is sorted by the raw column, not by the function result; the database would have to compute the function for every row.*
3. In `(customer_id, created_at DESC)`, which queries are served? *Those that fix `customer_id` and then filter or order by `created_at`, newest first.*
4. What does `INCLUDE (id, status, total)` add? *The extra columns are stored in the leaf pages so a query needing only those columns can be answered without visiting the table.*
5. What does `Heap Fetches: 0` mean in an index-only scan? *Every page was marked all-visible, so no table page had to be visited.*

## Further reading

- PostgreSQL 18, "Indexes": https://www.postgresql.org/docs/18/indexes.html — "Index Types" (B-tree), "Multicolumn Indexes", "Indexes and ORDER BY", "Index-Only Scans and Covering Indexes" (https://www.postgresql.org/docs/18/indexes-index-only-scans.html).
- `CREATE INDEX`: https://www.postgresql.org/docs/18/sql-createindex.html

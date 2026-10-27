# EXPLAIN and reading query plans

## What it is

A **query plan** is the step-by-step method PostgreSQL chooses to answer an SQL statement: which tables to read, in what way, which indexes to use, how to sort and combine. **`EXPLAIN`** prints the plan instead of (or as well as) running the statement. Reading plans is the central skill of this lesson: a plan tells you *why* a query is slow.

## Why this repository uses it

The deep-page problem is only visible in a plan: the same `LIMIT 20` costs 23 pages on page 1 and 200,751 on page 10,000. The README's claims about pagination are lines of the six plans in `sql/explain/`, and the Python code parses those plans to build the results table.

## Where it appears

| File | Role |
|---|---|
| `sql/explain/*.sql` (6 files) | The `EXPLAIN (ANALYZE, BUFFERS)` statement for each plan. |
| `sql/explain/*.txt` (6 files) | The captured output, rewritten by `make run`. |
| `sql/explain/results.md` | The table the replay builds from the plans. |
| `src/busy_listing/domain/plan.py` | Reads the text and JSON forms. |
| `src/busy_listing/infrastructure/lab_indexes.py` | `capture` runs a plan file twice and keeps the second. |
| `tests/integration/conftest.py`, `test_lesson_outcomes.py` | Use `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` and assert on the plan. |

## How it works underneath

**Variants.**

- `EXPLAIN SELECT ...` shows the plan the planner *would* use, with **estimates** (a guess based on statistics). The statement is not run.
- `EXPLAIN ANALYZE SELECT ...` **runs** the statement and adds **actual** numbers. Because it really executes, an `INSERT`, `UPDATE` or `DELETE` really happens; wrap it in a transaction and `ROLLBACK` to undo.
- Options go in brackets: `EXPLAIN (ANALYZE, BUFFERS, WAL, SERIALIZE, FORMAT JSON) ...`.
  - `BUFFERS` adds page counts: `shared hit=` (found in PostgreSQL's cache), `read=` (not found there, fetched from the operating system or disk), `dirtied=`, `written=`.
  - `WAL` adds write-ahead-log volume for statements that write: `WAL: records=... bytes=...`.
  - `SERIALIZE` (PostgreSQL 17 and newer) also measures the work of converting the result rows to the text sent to the client, including fetching out-of-line (TOAST) values; it adds a `Serialization:` line.
  - `FORMAT JSON` prints the same information as a JSON document, which programs parse easily.

**A plan is a tree.** The text is indented: the top line is the last step, which produces the result; lines starting with `->` are child steps feeding it. Data flows from the deepest steps up. Each step is a **node**.

**What each node line says.**

```text
Seq Scan on orders  (cost=0.00..78758.28 rows=5003 width=457) (actual time=0.455..830.145 rows=2748.00 loops=1)
```

- `Seq Scan on orders`: the node type and the table.
- `cost=0.00..78758.28`: the planner's estimate in arbitrary cost units: before the first row, and for all rows.
- `rows=5003`: *estimated* rows out of this node. `width=457`: estimated bytes per row.
- `actual time=0.455..830.145`: milliseconds until the first row and until the last row.
- `rows=2748.00`: *actual* rows (PostgreSQL 18 prints a fraction). If this differs by a lot from the estimate, the statistics are poor.
- `loops=1`: how many times the node ran; times and rows are per loop.

**Lines under a node.** `Filter:` (a condition applied to each row after reading it), `Rows Removed by Filter:` (rows read and thrown away: a high number is wasted work), `Index Cond:` (a condition handled by the index), `Recheck Cond:`, `Sort Key:`, `Sort Method:` (`quicksort`, `top-N heapsort`: keeping only the best N rows, `external merge`: spilled to disk), `Heap Blocks:`, `Heap Fetches:` (table visits made by an index-only scan), `Index Searches:` (how many separate descents of the index tree; PostgreSQL 18), `Buffers:`, `I/O Timings:` (time waiting for reads; needs `track_io_timing = on`).

**The footer.** `Planning Time:` (time choosing the plan), `Serialization:` (time and size of the output), `Execution Time:` (total, in milliseconds).

**How to read one.**

1. Start at the deepest node: how is the table read (`Seq Scan`, `Index Scan`...)?
2. Compare estimated and actual rows at each node.
3. Look for wasted work: `Rows Removed by Filter`, a `Sort` where an index could provide order, large `Buffers`.
4. Compare *pages touched* (hit + read), which does not depend on the machine's speed, as well as milliseconds, which does.

## Walkthrough of this repository's use

### The `.sql` files

`sql/explain/e1_offset_page10000.sql`, lines 1 to 4:

```sql
-- Step 3, page 10,000 by offset: OFFSET 199980 produces 200,000 rows and keeps the last 20.
SET timezone = 'UTC';
EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET 199980;
```

A comment, `SET timezone = 'UTC'`, then `EXPLAIN (ANALYZE, BUFFERS)` and the query. `ANALYZE` runs it; `BUFFERS` adds page counts. The six files are `e1_offset_page1`, `e1_offset_page100`, `e1_offset_page10000` (offset paging), `e2_keyset_page1`, `e2_keyset_page10000` (keyset paging with the original index) and `e3_keyset_page10000_covering` (keyset with the covering index).

### Reading page 10,000 by offset

`sql/explain/e1_offset_page10000.txt`, lines 1 to 7:

```text
Limit  (cost=14936.53..14938.02 rows=20 width=49) (actual time=188.438..188.463 rows=20.00 loops=1)
  Buffers: shared hit=200751
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.027..181.132 rows=200000.00 loops=1)
        Index Searches: 1
        Buffers: shared hit=200751
Planning Time: 0.224 ms
Execution Time: 188.513 ms
```

1. `Limit  (cost=14936.53..14938.02 rows=20 width=49) (actual time=188.438..188.463 rows=20.00 loops=1)`: the top node keeps 20 rows. Estimated cost 14,936 to 14,938, 20 rows of 49 bytes; actually it finished in 188 ms and returned 20 rows.
2. `Buffers: shared hit=200751`: 200,751 pages touched, all found in the cache. This is the number that tells the story: 23 pages for page 1.
3. `->  Index Scan using idx_orders_created_id on orders ... (actual time=0.027..181.132 rows=200000.00 loops=1)`: the child node. It read the ordering index and returned **200,000 rows** to the `Limit`, which kept the last 20. Nothing is "skipped": 199,980 rows were produced and discarded. 181 of the 188 ms are spent here.
4. `Index Searches: 1`: the index tree was descended once (PostgreSQL 18 prints this).
5. `Planning Time` (0.224 ms) and `Execution Time: 188.513 ms`.

Compare the two shallower pages:

`sql/explain/e1_offset_page1.txt`, lines 1 to 7:

```text
Limit  (cost=0.42..1.92 rows=20 width=49) (actual time=0.009..0.031 rows=20.00 loops=1)
  Buffers: shared hit=23
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.009..0.029 rows=20.00 loops=1)
        Index Searches: 1
        Buffers: shared hit=23
Planning Time: 0.048 ms
Execution Time: 0.041 ms
```

Page 1: `rows=20.00` from the index scan, 23 pages, 0.041 ms. Page 100 (`e1_offset_page100.txt`): 2,000 rows from the scan, 2,010 pages, 1.1 ms. The cost grows with the offset, as the table in the README shows.

### Reading page 10,000 by keyset

`sql/explain/e2_keyset_page10000.txt`, lines 1 to 8:

```text
Limit  (cost=0.42..2.19 rows=20 width=32) (actual time=0.007..0.016 rows=20.00 loops=1)
  Buffers: shared hit=23
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..70530.77 rows=797620 width=32) (actual time=0.007..0.014 rows=20.00 loops=1)
        Index Cond: (ROW(created_at, id) < ROW('2026-05-04 11:02:00+00'::timestamp with time zone, 832765))
        Index Searches: 1
        Buffers: shared hit=23
Planning Time: 0.024 ms
Execution Time: 0.022 ms
```

The same top node, the same index, but now `Index Cond: (ROW(created_at, id) < ROW('2026-05-04 11:02:00+00'::timestamp with time zone, 832765))`: the condition is handled by the index, which seeks to that position. The index scan returns `rows=20.00` (not 200,000) in 0.014 ms and the page count is 23, the same as page 1. Note the estimate on the scan, `rows=797620`: the planner knows roughly how many rows are "older than" the bookmark, but the `Limit` above stops the scan after 20.

### Reading the covering plan

`sql/explain/e3_keyset_page10000_covering.txt`, lines 1 to 9:

```text
Limit  (cost=0.42..1.33 rows=20 width=32) (actual time=0.007..0.021 rows=20.00 loops=1)
  Buffers: shared hit=5
  ->  Index Only Scan using idx_orders_listing on orders  (cost=0.42..36037.91 rows=800542 width=32) (actual time=0.007..0.019 rows=20.00 loops=1)
        Index Cond: (ROW(created_at, id) < ROW('2026-05-04 11:02:00+00'::timestamp with time zone, 832765))
        Heap Fetches: 0
        Index Searches: 1
        Buffers: shared hit=5
Planning Time: 0.034 ms
Execution Time: 0.030 ms
```

`Index Only Scan using idx_orders_listing`: answered from the index alone. `Heap Fetches: 0`: no table page was visited. `Buffers: shared hit=5`: 5 pages against 23.

### The Python side

`src/busy_listing/infrastructure/lab_indexes.py`, lines 39 to 45:

```python
    def capture(self, name: str) -> tuple[str, ...]:
        """Run `explain/<name>.sql` twice (the first run warms the cache) and return the second plan's lines."""
        path = self._sql_dir / "explain" / f"{name}.sql"
        with session(self._settings) as connection:
            run_file(connection, path)
            rows = run_file(connection, path)
        return tuple(row[0] for row in rows)
```

`capture(name)` runs the file twice on one connection (the first run warms the cache) and returns the lines of the second plan. `parse_text_plan` (regular-expressions note) extracts `execution_ms`, `pages`, the node types and the index names; the replay saves the text to the `.txt` file and puts the numbers in the "Plans for the deep page" table of `results.md`.

### JSON form in the tests

`tests/integration/test_lesson_outcomes.py`, lines 81 to 88:

```python
def test_step3_offset_reads_and_discards_every_row_before_the_page(connection, indexes):
    plans = {offset: explain(connection, OFFSET_PAGE.format(offset=offset)) for offset in (0, 1980, 199980)}
    deep_summary, deep_json = plans[199980]
    assert deep_json["Plan"]["Node Type"] == "Limit"
    assert deep_json["Plan"]["Actual Rows"] == 20
    assert deep_json["Plan"]["Plans"][0]["Actual Rows"] == 199_980 + 20, "200,000 rows produced to keep 20"
    assert plans[0][0].pages < plans[1980][0].pages < deep_summary.pages
    assert deep_summary.execution_ms > 20 * plans[0][0].execution_ms
```

`explain(connection, query)` (in `conftest.py`) runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` and returns the parsed summary and the raw dictionary. The test reads `deep_json["Plan"]["Plans"][0]["Actual Rows"] == 199_980 + 20`: the child node produced 200,000 rows to keep 20, which is the offset problem as an assertion.

## Try it yourself

(After `make up db`.)

1. `cat sql/explain/e1_offset_page10000.txt` — read the plan above in your own file.
2. `docker compose exec -T db psql -U lab -d lab < sql/explain/e1_offset_page10000.sql` — runs the statement and prints a fresh plan; compare `Buffers` and `Execution Time` with the file.
3. `docker compose exec db psql -U lab -d lab -c "explain select * from orders order by created_at desc, id desc limit 20 offset 199980"` — only the estimate, no execution time, no buffers.
4. `docker compose exec db psql -U lab -d lab -c "explain (analyze, buffers, format json) select count(*) from orders"` — the JSON form.
5. `.venv/bin/python -c "from busy_listing.domain.plan import parse_text_plan; p=parse_text_plan(open('sql/explain/e3_keyset_page10000_covering.txt').read().splitlines()); print(p.node_types, p.heap_fetches, p.pages)"` — prints `('Limit', 'Index Only Scan') 0 5`.

## Mistakes people make

- Running `EXPLAIN ANALYZE` on an `UPDATE` or `DELETE` in production without a transaction.
- Trusting one run: the first run may be slow because the cache is cold. Run twice and read the second.
- Comparing milliseconds across machines; compare ratios and page counts.
- Ignoring the estimate-versus-actual gap.
- Reading only the top line.
- Forgetting that `EXPLAIN` without `ANALYZE` does not show whether the index really helps.

**How this repository avoids them.** Plans are run twice and the second kept; the comparison shows pages touched next to milliseconds; `results.md` says how busy the machine was; the parsed numbers are asserted in tests (JSON plans from the live database) and the committed text plans are the evidence in the README.

## Check yourself

1. What is the difference between `EXPLAIN` and `EXPLAIN ANALYZE`? *The first shows the estimated plan without running the statement; the second runs it and adds actual times and row counts.*
2. What does `Rows Removed by Filter: 997252` tell you? *The scan read about a million rows and discarded almost all of them: wasted work an index could avoid.*
3. What do `shared hit=2058 read=61692` mean? *2,058 pages were found in PostgreSQL's cache and 61,692 were not, so they were fetched from outside it.*
4. Why prefer page counts to milliseconds when comparing two plans? *Page counts do not depend on how busy or fast the machine is.*
5. What does `SERIALIZE` add? *The cost of turning the result rows into the text sent to the client, including detoasting.*

## Further reading

- PostgreSQL 18, "Using EXPLAIN": https://www.postgresql.org/docs/18/using-explain.html
- `EXPLAIN` command reference (options): https://www.postgresql.org/docs/18/sql-explain.html

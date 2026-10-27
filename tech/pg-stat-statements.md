# pg_stat_statements

## What it is

**`pg_stat_statements`** is a PostgreSQL **extension** (an optional add-on that ships with the server) that keeps a running tally of every SQL statement the server executes: how many times it ran, how much total time it took, how many rows it returned, how many pages it touched. You read the tally through a view of the same name. It answers the question "where does the database spend its time?" without guessing, and it is the main evidence of the "busy listing" lesson.

## Why this repository uses it

It is the lesson. "Fix a busy listing from the database's own statistics" means: do not guess which query is slow, ask the database. The replay resets the statistics, sends the same 300 requests, and ranks what the database says it ran, four times, once per version of the listing.

## Where it appears

| File | Role |
|---|---|
| `docker-compose.yml` | Preloads the library and sets `track_utility` and `max`. |
| `sql/001_schema.sql` | `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`. |
| `sql/003_queries.sql` | The two rankings as plain SQL, and the reset. |
| `src/busy_listing/infrastructure/pg_stat_statements.py` | The adapter: `reset()` and `snapshot()`. |
| `src/busy_listing/domain/statements.py` | Merging rows with the same text, and the two rankings. |
| `src/busy_listing/application/replay.py` | When to reset and when to read. |
| `.github/workflows/ci.yml` | Preloads the library in the CI service container. |
| `src/busy_listing/infrastructure/health_probes.py` | The health check requires the extension to be installed. |

## How it works underneath

**Loading.** The extension must be loaded when the server starts: `shared_preload_libraries = 'pg_stat_statements'` in the server settings. It then watches all statements in shared memory. To use the view in a database you run `CREATE EXTENSION pg_stat_statements;` once there.

**Normalization.** Statements are counted by shape, not by value. `SELECT ... WHERE id = 5` and `... WHERE id = 7` become one entry `SELECT ... WHERE id = $1`. Each entry has a `queryid` (a number computed from the statement's shape *and the types of its parameters*), the `query` text, and counters.

**Columns used here.** `query` (the normalized text), `calls` (how many times it ran), `total_exec_time` (total milliseconds spent executing it), `mean_exec_time` (average), and `dbid` (which database it belongs to; compare with `pg_database.oid`).

**Settings.** `pg_stat_statements.track_utility = off` leaves out utility commands (`BEGIN`, `COMMIT`, `SET`, `VACUUM`); `pg_stat_statements.max = 5000` limits how many distinct statements are remembered.

**Reset.** `SELECT pg_stat_statements_reset();` clears the counters, so you can measure exactly one piece of work: reset, run the load, read.

**Two rankings.** *By total time* (`ORDER BY total_exec_time DESC`) shows where the database spends its time; *by calls* (`ORDER BY calls DESC`) shows what the application asks for most. They often differ: a statement that costs 0.005 ms but runs 6,000 times is top of the second list and invisible in the first, and a statement that costs 17 ms and runs 300 times is the reverse.

**A subtlety about parameter types.** A driver may send a small integer as `int2`, a medium one as `int4` and a big one as `int8`. The statement text is identical, but PostgreSQL treats each as a separate statement with its own `queryid`. So the same text can appear on several rows, and the counts of one statement are split. This repository merges rows with identical text before ranking.

## Walkthrough of this repository's use

### Loading and creating

`docker-compose.yml`, lines 13 to 20:

```yaml
    command:
      - postgres
      - -c
      - shared_preload_libraries=pg_stat_statements
      - -c
      - pg_stat_statements.track_utility=off
      - -c
      - pg_stat_statements.max=5000
```
`sql/001_schema.sql`, lines 1 to 3:

```sql
-- 001_schema.sql: DDL for the "Busy listing" lab (PostgreSQL 18). Safe to run twice: IF NOT EXISTS throughout, one transaction.
-- pg_stat_statements is the evidence source; it needs shared_preload_libraries (set in docker-compose.yml).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

The server is started with `shared_preload_libraries=pg_stat_statements`, `pg_stat_statements.track_utility=off` and `pg_stat_statements.max=5000` (Compose note). The schema file then runs `CREATE EXTENSION IF NOT EXISTS pg_stat_statements;`, which creates the view in the `lab` database; `IF NOT EXISTS` makes it safe to run twice.

### The two rankings as SQL

`sql/003_queries.sql`, lines 23 to 34:

```sql
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
```

`SELECT pg_stat_statements_reset() IS NOT NULL AS statistics_reset;` clears the counters (the function returns a value in PostgreSQL 18, so the `IS NOT NULL` turns it into a printable `t`). The two queries select `left(query, 80)` (the first 80 characters of the statement), `calls`, `round(total_exec_time::numeric, 1)` and `round(mean_exec_time::numeric, 3)`, only for this database (`dbid = (SELECT oid FROM pg_database WHERE datname = current_database())`) and without the monitoring query itself (`query NOT ILIKE '%pg_stat_statements%'`; `ILIKE` is a case-insensitive `LIKE`, `%` matches any text), once ordered by `total_exec_time DESC` and once by `calls DESC`, `LIMIT 10`.

### The adapter

`src/busy_listing/infrastructure/pg_stat_statements.py`, lines 1 to 30:

```python
"""Adapter: the database's own statistics. Implements `StatementStatistics`."""

from __future__ import annotations

from ..domain.statements import StatementStat
from .postgres import session
from .settings import PostgresSettings

# Only this database's application statements: not the ranking queries, not the extension's own calls.
_APPLICATION_STATEMENTS = """
    FROM pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND query NOT ILIKE '%pg_stat_statements%' AND query NOT ILIKE '%pg_database%'
"""


class PgStatStatements:
    """Reads and resets `pg_stat_statements`."""

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def reset(self) -> None:
        with session(self._settings) as connection:
            connection.execute("SELECT pg_stat_statements_reset()")

    def snapshot(self) -> list[StatementStat]:
        with session(self._settings) as connection:
            rows = connection.execute(f"SELECT query, calls, total_exec_time {_APPLICATION_STATEMENTS}").fetchall()
        return [StatementStat(str(query), int(calls), float(total)) for query, calls, total in rows]
```

`_APPLICATION_STATEMENTS` is the shared `FROM ... WHERE` text of the snapshot (the same filter as the SQL above, with `pg_database` also excluded because the filter's own subquery mentions it). `reset()` runs `SELECT pg_stat_statements_reset()`. `snapshot()` selects `query, calls, total_exec_time` and turns each row into a `StatementStat` (`str(query)`, `int(calls)`, `float(total)`). Each call opens its own short connection (psycopg note). This class implements the `StatementStatistics` port, so the use case never sees SQL.

### Merging by text, then ranking

`src/busy_listing/domain/statements.py`, lines 1 to 6:

```python
"""Statements as `pg_stat_statements` reports them, and how the lesson ranks them.

The view keys its rows by a query id that includes parameter types, and the driver sends an integer parameter as
`int2`, `int4` or `int8` depending on its value, so one SQL text can appear under several ids. Ranking the rows as
they are would split one statement's calls and understate it, so rows with the same text are added together.
"""
```
`src/busy_listing/domain/statements.py`, lines 41 to 55:

```python
def merge_by_text(rows: Iterable[StatementStat]) -> list[StatementStat]:
    """Add together the rows that have the same query text."""
    calls: dict[str, int] = defaultdict(int)
    total: dict[str, float] = defaultdict(float)
    for row in rows:
        calls[row.query] += row.calls
        total[row.query] += row.total_ms
    return [StatementStat(query, calls[query], total[query]) for query in calls]


def rank(rows: Iterable[StatementStat], by: RankBy, limit: int = 10) -> list[StatementStat]:
    """The top `limit` statements by total time or by calls (ties keep their input order)."""
    merged = merge_by_text(rows)
    key = (lambda row: row.total_ms) if by is RankBy.TOTAL_TIME else (lambda row: float(row.calls))
    return sorted(merged, key=key, reverse=True)[:limit]
```

The module docstring explains the subtlety above. `merge_by_text` adds `calls` and `total_ms` of all rows with the same `query` using two `defaultdict`s (dictionaries that start every missing key at 0). `rank(rows, by, limit=10)` merges, then sorts by total time or by calls, largest first (`reverse=True`), and keeps the top ten. `key = (lambda row: row.total_ms) if by is RankBy.TOTAL_TIME else (lambda row: float(row.calls))` chooses the sort key with a conditional expression of two small functions.

### When the replay reads it

`src/busy_listing/application/replay.py`, lines 93 to 111:

```python
    def _measure(self, phase: lesson.Phase) -> PhaseResult:
        bookmarks = self._driver.prepare(phase.strategy)
        self._driver.run(phase.strategy, 5, bookmarks)  # warm the caches; not measured
        self._statistics.reset()
        timings = self._driver.run(phase.strategy, self._requests, bookmarks)
        rows = self._statistics.snapshot()
        result = PhaseResult(
            label=phase.label,
            by_time=tuple(rank(rows, RankBy.TOTAL_TIME)),
            by_calls=tuple(rank(rows, RankBy.CALLS)),
            database_ms=total_time_ms(rows),
            statements=total_calls(rows),
            wall_seconds=timings.wall_seconds,
            median_ms_by_page=timings.median_by_page(),
        )
        self._progress(
            f"{self._requests} requests in {result.wall_seconds:.1f} s, database time {result.database_ms:.0f} ms"
        )
        return result
```

For each phase: `self._driver.run(phase.strategy, 5, bookmarks)` sends five warm-up requests (not measured); `self._statistics.reset()` clears the counters; `self._driver.run(..., self._requests, ...)` sends the 300 measured requests; `rows = self._statistics.snapshot()` reads the counters. Then `rank(rows, RankBy.TOTAL_TIME)` and `rank(rows, RankBy.CALLS)` give the two top lists, `total_time_ms(rows)` the database time of the whole load and `total_calls(rows)` the number of statements.

What the first phase shows (`sql/explain/results.md`): by total time the top statement is the `OFFSET` listing query (300 calls, tens of milliseconds each); by calls the top statement is `SELECT customers ... WHERE customers.id = $1` (6,000 calls, hundredths of a millisecond each). Different statements, which is the first "Done when" line of the lesson.

## Try it yourself

(After `make up db`.)

1. `docker compose exec db psql -U lab -d lab -c "show shared_preload_libraries"` prints `pg_stat_statements`.
2. `docker compose exec db psql -U lab -d lab -c "select count(*) from pg_stat_statements"` prints a small number (the statements run so far).
3. `make run`, then `docker compose exec db psql -U lab -d lab -c "select left(query, 60) as q, calls, round(total_exec_time::numeric,1) as total_ms from pg_stat_statements where query not ilike '%pg_stat_statements%' order by calls desc limit 5"` lists the busiest statements of the last phase.
4. `docker compose exec db psql -U lab -d lab -c "select pg_stat_statements_reset() is not null"` clears the counters; run command 2 again to see them start from zero.
5. `.venv/bin/python -c "from busy_listing.domain.statements import *; r=[StatementStat('q',3000,15.0),StatementStat('q',3000,18.0)]; print(merge_by_text(r))"` prints `[StatementStat(query='q', calls=6000, total_ms=33.0)]`.

## Mistakes people make

- Forgetting `shared_preload_libraries` (the extension then does nothing; the view errors).
- Reading the view without resetting it first, so old work is mixed in.
- Ranking only by total time, or only by calls.
- Counting rows of the same text under different `queryid`s as different statements.
- Including the monitoring queries in the ranking.

**How this repository avoids them.** The library is preloaded by the compose file and by CI. Every phase resets the counters first and runs warm-up requests that are not counted. The filter keeps the monitoring queries out. Rows with the same text are merged before ranking. A test checks that the top-by-time and top-by-calls statements differ.

## Check yourself

1. How do two statements with different literal values appear in the view? *As one row, with the values replaced by `$1`, `$2`.*
2. Why must the extension be preloaded? *It has to watch statements from the start of the server, in shared memory.*
3. What does `pg_stat_statements_reset()` do? *Clears the counters.*
4. What is the difference between the two rankings? *Total time shows where time is spent; calls shows what is asked most often.*
5. Why can one statement text have several rows? *The query id includes the parameter types, and a driver may send the same value as different integer types.*

## Further reading

- PostgreSQL 18, `pg_stat_statements`: https://www.postgresql.org/docs/18/pgstatstatements.html

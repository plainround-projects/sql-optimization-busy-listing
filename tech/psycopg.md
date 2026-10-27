# psycopg 3

## What it is

**psycopg** (version 3) is the Python library that talks to a PostgreSQL server. Your Python code opens a **connection**, sends SQL text, and receives rows back as Python values. Underneath it uses **libpq**, the C library from PostgreSQL itself that implements the network protocol.

## Why this repository uses it

Two things in this repository talk to PostgreSQL directly with psycopg: the lab tooling (index changes, plan capture, the statistics view, bookmarks for keyset paging, health checks) and, underneath SQLAlchemy, the ORM itself, which uses psycopg 3 as its driver (`postgresql+psycopg://`). Pinned as `psycopg==3.3.6` and `psycopg-binary==3.3.6`.

## Where it appears

| File | Use |
|---|---|
| `infrastructure/postgres.py` | `connect`, `session`, `scalar`: every direct connection is opened here. |
| `infrastructure/lab_indexes.py` | Rebuilds indexes, runs migration files and plan files. |
| `infrastructure/pg_stat_statements.py` | `reset()` and `snapshot()`. |
| `infrastructure/http_load.py` | `prepare()` looks up the bookmark row of each deep page. |
| `infrastructure/health_probes.py` | The health queries and the translation of `psycopg.Error`. |
| `infrastructure/sql_script.py` | `run_file` runs statements on a connection. |
| `infrastructure/orm.py` | SQLAlchemy uses psycopg underneath (SQLAlchemy note). |
| `tests/integration/*` | Open connections to check results. |
| `pyproject.toml` | `dependencies = [..., "psycopg[binary]>=3.2,<4", ...]`. |
| `domain/` and `application/` | Never import psycopg: import-linter forbids it. |

## How it works underneath

**Connection.** `psycopg.connect(host=..., port=..., dbname=..., user=..., password=..., connect_timeout=...)` opens a network (TCP) connection to the server, which starts a dedicated server process for it, and logs in. `connect_timeout` limits how long to wait, in seconds. The keyword `options` passes server settings for the session in the form `-c name=value`.

**Cursor and `execute`.** A **cursor** sends a statement and holds its result. `connection.execute("SELECT ...")` is a shortcut: it creates a cursor, runs the statement and returns the cursor. `cursor.fetchone()` returns the next row (a Python tuple) or `None`; `fetchall()` returns all remaining rows as a list. `cursor.description` is `None` when the statement returns no rows (an `INSERT`, `CREATE INDEX`...) and describes the columns when it does.

**Parameters.** `execute("... WHERE id = %s", (5,))` sends the value separately from the statement text (the server substitutes it, "server-side binding"). Never build SQL by pasting user text into a string: that is how SQL injection happens. A table or index *name* cannot be a parameter; code that must put a name into SQL builds the text itself, from a fixed list.

**Transactions and autocommit.** A **transaction** is a group of statements that succeed or fail together. With `autocommit=False` (the default) psycopg opens a transaction before your first statement and keeps it open until you call `commit()` or `rollback()`, or leave a `with connection:` block. With `autocommit=True` each statement is its own transaction and is saved at once. Some commands cannot run inside a transaction (`VACUUM`, `CREATE INDEX CONCURRENTLY`), so they need autocommit.

**Types.** Python `int`, `str`, `float`, `datetime`, `Decimal`, `list`, `dict` (as JSON) are converted to and from PostgreSQL types automatically. A row is a tuple unless you ask for something else.

**Errors.** Base class `psycopg.Error`; `psycopg.OperationalError` for connection problems and server shutdowns; `psycopg.errors.QueryCanceled` when a statement hits `statement_timeout`; many others named after PostgreSQL error codes.

**Installing.** `pip install "psycopg[binary]"` installs `psycopg` plus `psycopg-binary`, a precompiled version bundled with libpq, which needs no compiler and no PostgreSQL client libraries. `psycopg[c]` builds from source. Plain `psycopg` is pure Python and needs a libpq installed on the system.

**Closing.** A connection holds a server process; close it (`connection.close()`) or use a `with` block.

## Walkthrough of this repository's use

### Opening a connection

`src/busy_listing/infrastructure/postgres.py`, lines 1 to 45:

```python
"""Adapter: connections to PostgreSQL, with a connect timeout, a statement timeout and retries with backoff."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from .logging import fields
from .retry import retry
from .settings import PostgresSettings

logger = logging.getLogger(__name__)


def connect(settings: PostgresSettings, attempts: int = 5, *, autocommit: bool = True) -> psycopg.Connection[Any]:
    """Open a connection; parallel query is off for the session so plans read the same on every server."""

    def open_connection() -> psycopg.Connection[Any]:
        return psycopg.connect(
            host=settings.host,
            port=settings.port,
            dbname=settings.database,
            user=settings.user,
            password=settings.password,
            connect_timeout=settings.connect_timeout_seconds,
            options=(
                f"-c statement_timeout={settings.statement_timeout_ms} "
                f"-c max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather}"
            ),
            autocommit=autocommit,
        )

    return retry(
        open_connection,
        attempts=attempts,
        base_delay_seconds=0.5,
        retry_on=(psycopg.OperationalError,),
        on_retry=lambda attempt, error: logger.warning(
            "retrying database connection", extra=fields(attempt=attempt, error=error)
        ),
    )
```

- `connect(settings, attempts=5, *, autocommit=True)` returns a `psycopg.Connection[Any]`. It defines an inner function `open_connection` and passes it to `retry`.
- `psycopg.connect(...)` gets the host, port, database name (`dbname=`), user and password from the settings, `connect_timeout=settings.connect_timeout_seconds` (5 seconds by default) and `autocommit=autocommit`.
- `options=(f"-c statement_timeout={settings.statement_timeout_ms} " f"-c max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather}")` (two adjacent strings joined) sets two server settings for this session only: `statement_timeout` (a statement that runs longer than 120,000 ms is cancelled) and `max_parallel_workers_per_gather` (0: no parallel workers, so plans read the same everywhere). This is why the Compose file and the connection both say `0`.
- `retry(open_connection, attempts=5, base_delay_seconds=0.5, retry_on=(psycopg.OperationalError,), on_retry=lambda attempt, error: logger.warning(...))` retries only connection failures, with exponential backoff (standard-library note), and logs each failed attempt.
- `session(...)` (lines 48 to 55) wraps the connection in a context manager that always closes it.
- `scalar(connection, query)` runs `connection.execute(query).fetchone()` and returns `row[0]` — the first column of the first row.

### Index changes and plan files

`src/busy_listing/infrastructure/lab_indexes.py`, lines 1 to 45:

```python
"""Adapter: the index state of the orders table and the plan files. Implements `IndexLayout` and `PlanCapture`."""

from __future__ import annotations

from pathlib import Path

from .postgres import session
from .settings import PostgresSettings
from .sql_script import run_file

LESSON_INDEXES = ("idx_orders_created_id", "idx_orders_listing")


class PostgresLabIndexes:
    """Moves the table between the original ordering index and the covering index, using the migration files."""

    def __init__(self, settings: PostgresSettings, sql_dir: Path) -> None:
        self._settings = settings
        self._sql_dir = sql_dir

    def migrations(self) -> list[Path]:
        """The up migrations in order."""
        return sorted((self._sql_dir / "migrations").glob("*.sql"))

    def down_migrations(self) -> list[Path]:
        """The down scripts in order."""
        return sorted((self._sql_dir / "migrations" / "down").glob("*.sql"))

    def reset_to(self, step: int) -> None:
        """Rebuild the original ordering index, then apply migrations 1 to `step`; refresh statistics."""
        with session(self._settings) as connection:
            for name in LESSON_INDEXES:
                connection.execute(f"DROP INDEX IF EXISTS {name}")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC)")
            for path in self.migrations()[:step]:
                run_file(connection, path)
            connection.execute("VACUUM ANALYZE orders")

    def capture(self, name: str) -> tuple[str, ...]:
        """Run `explain/<name>.sql` twice (the first run warms the cache) and return the second plan's lines."""
        path = self._sql_dir / "explain" / f"{name}.sql"
        with session(self._settings) as connection:
            run_file(connection, path)
            rows = run_file(connection, path)
        return tuple(row[0] for row in rows)
```

- `PostgresLabIndexes` opens a **new connection per operation** (`with session(self._settings) as connection:`).
- `migrations()` / `down_migrations()` list the files with `Path.glob("*.sql")` and `sorted(...)`, so `001_...` comes before `002_...`.
- `reset_to(step)`: for each name in `LESSON_INDEXES` it runs `DROP INDEX IF EXISTS {name}` (an f-string: an index name cannot be a parameter, and here it comes from a fixed constant tuple, not from user input); then `CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC)` recreates the original ordering index; then `run_file` applies migrations `1..step` using the slice `self.migrations()[:step]`; finally `VACUUM ANALYZE orders` refreshes statistics and the visibility map. With the default `autocommit=True` of `session`, each statement commits at once, which `VACUUM` requires.
- `capture(name)` runs `sql/explain/<name>.sql` **twice** on the same connection (the first run warms the cache) and returns the lines of the second plan: `run_file` returns the rows of the last statement that returns rows, here the `EXPLAIN` output, and `tuple(row[0] for row in rows)` takes the first column of each row.

### The statistics view

`src/busy_listing/infrastructure/pg_stat_statements.py`, lines 17 to 30:

```python
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

`connection.execute("SELECT pg_stat_statements_reset()")` and `connection.execute(f"SELECT query, calls, total_exec_time {_APPLICATION_STATEMENTS}").fetchall()` (pg_stat_statements note). `fetchall()` returns a list of tuples; the list comprehension unpacks each into `query, calls, total` and converts the types.

### The bookmark lookup, with a parameter

`src/busy_listing/infrastructure/http_load.py`, lines 38 to 53:

```python
    def prepare(self, strategy: Strategy) -> Bookmarks:
        """For keyset paging, the cursor of the row before each page; empty for the other strategies."""
        if strategy is not Strategy.KEYSET:
            return {}
        bookmarks: dict[int, str | None] = {}
        with session(self._postgres) as connection:
            for page in PAGES:
                if page == 0:
                    bookmarks[page] = None
                    continue
                row = connection.execute(
                    "SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1",
                    (page * PAGE_SIZE - 1,),
                ).fetchone()
                bookmarks[page] = Cursor(row[0], row[1]).encode() if row else None
        return bookmarks
```

For keyset paging the load needs, for each deep page, the cursor of the row just before it. `connection.execute("SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1", (page * PAGE_SIZE - 1,))` passes the offset as a **parameter**: `%s` is the placeholder and the one-item tuple `(page * PAGE_SIZE - 1,)` holds the value (the trailing comma makes it a tuple). `.fetchone()` returns the row as a tuple `(created_at, id)` or `None`; `Cursor(row[0], row[1]).encode() if row else None`. Python's `datetime` comes back from a `timestamptz` column with a time zone, ready for the cursor. This uses an `OFFSET` once per page, before the timed run, so it is not part of what the lesson measures.

### Health probe

`src/busy_listing/infrastructure/health_probes.py`, lines 12 to 33:

```python
class PostgresListingProbe:
    """Healthy when PostgreSQL answers, the orders are seeded and pg_stat_statements is loaded."""

    name = "postgres"

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def check(self) -> str:
        try:
            with session(self._settings) as connection:
                if scalar(connection, "SELECT to_regclass('public.orders')") is None:
                    raise ProbeFailedError("the orders table is missing; run make db")
                rows = scalar(connection, "SELECT count(*) FROM orders")
                extension = scalar(connection, "SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
        except psycopg.Error as error:
            raise ProbeFailedError(f"cannot query PostgreSQL: {error}") from error
        if rows == 0:
            raise ProbeFailedError("the orders table is empty; run make db")
        if extension == 0:
            raise ProbeFailedError("pg_stat_statements is not installed; run make db")
        return f"{rows:,} orders, pg_stat_statements loaded"
```

Three queries: `to_regclass('public.orders')` returns `NULL` (Python `None`) when the table does not exist; `count(*)`; and `count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'` (is the extension installed?). Any `psycopg.Error` is turned into the application's `ProbeFailedError` with `raise ... from error`; so `application/` never sees psycopg.

## Try it yourself

(After `make up db`, with `.env` loaded: `set -a; . ./.env; set +a`.)

1. `make health` prints `ok postgres: 1,000,000 orders, pg_stat_statements loaded`.
2. Ask the server three questions through a session. Run:

   ```bash
   .venv/bin/python - <<'EOF'
   from busy_listing.infrastructure.postgres import session
   from busy_listing.infrastructure.settings import Settings
   with session(Settings.from_env().postgres) as c:
       print(c.execute("select version()").fetchone()[0])
       print(c.execute("show statement_timeout").fetchone())
       print(c.execute("show max_parallel_workers_per_gather").fetchone())
   EOF
   ```

   (`python -` reads the program from standard input; `<<'EOF' ... EOF` is a **here-document**, a way to give a shell command several lines of input.) It prints the PostgreSQL version line (`PostgreSQL 18.x ...`), `('1min',)` and `('0',)`: the two session settings were passed through `options`.
3. `echo $?` after it prints `0`.
4. `.venv/bin/python -c "from busy_listing.infrastructure.lab_indexes import PostgresLabIndexes as P; from busy_listing.infrastructure.settings import Settings as S; s=S.from_env(); print([p.name for p in P(s.postgres, s.sql_dir).migrations()])"` prints `['001_expand_covering_listing_index.sql', '002_contract_drop_old_listing_index.sql']`.
5. `make down` and run command 2 again: you see four `retrying database connection` warnings with growing pauses (five attempts are made) and then a `psycopg.OperationalError`.

## Mistakes people make

- Building SQL with f-strings from user input.
- Leaving a transaction open (a default connection after `SELECT` is "idle in transaction", holding resources and blocking maintenance).
- Forgetting `commit()` and losing changes.
- Running `VACUUM` in a transaction (PostgreSQL refuses).
- Not closing connections.
- Assuming a fetched row is a dictionary (it is a tuple unless a row factory is chosen).

**How this repository avoids them.** Connections are always closed (`finally`). Only the migration files and the plan files are executed; no user text is pasted into SQL, and the one f-string (`DROP INDEX IF EXISTS {index}`) uses names from a constant tuple. `VACUUM` runs on an autocommit connection. The write-cost batches run in a transaction that is rolled back, and the replay checks that the row count did not change.

## Check yourself

1. What does `connection.execute(sql)` return? *A cursor holding the result.*
2. When does `cursor.description` equal `None`? *When the statement returns no rows.*
3. What does `autocommit=True` change? *Every statement is committed on its own; no transaction stays open.*
4. Why pass values as parameters (`%s`) and not paste them into the SQL? *To avoid SQL injection and quoting errors; the value never becomes part of the statement text.*
5. What is `psycopg-binary`? *A precompiled, self-contained implementation that makes `pip install` need no compiler or libpq.*

## Further reading

- Psycopg 3 documentation (3.3): https://www.psycopg.org/psycopg3/docs/ — "Basic module usage", "Transactions management", "Installation".
- PostgreSQL libpq connection parameters: https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-PARAMKEYWORDS

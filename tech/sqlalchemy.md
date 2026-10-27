# SQLAlchemy

## What it is

**SQLAlchemy** is a Python library for working with relational databases. It has two layers. The **Core** builds SQL statements from Python expressions (`select(Order.id).where(...)`) and runs them. The **ORM** (Object-Relational Mapper) sits on top: you describe each table as a Python class, a row becomes an object of that class, and a link between tables becomes an attribute (`order.customer`). The library sends SQL to the database through a **driver** (here psycopg).

## Why this repository uses it

The lesson is about the problems an ORM creates when used naively: the N+1 of a lazy relationship and the cost of loading whole objects for a listing. SQLAlchemy 2 is the ORM; the `naive` version of the listing uses it the way a careless application would, and the `batched` and `keyset` versions use it the way a careful one would, so the effect shows in `pg_stat_statements`.

## Where it appears

| File | Role |
|---|---|
| `src/busy_listing/infrastructure/orm.py` | The mapped classes `Customer` and `Order`, and `create_lab_engine`. |
| `src/busy_listing/infrastructure/sqlalchemy_orders.py` | `SqlAlchemyOrders`: the three ways to list a page. |
| `src/busy_listing/interfaces/common.py` | Creates the engine and the repository (`build_app`). |
| `tests/integration/conftest.py` | The `engine`, `orders` and `statement_counter` fixtures. |
| `pyproject.toml` | `sqlalchemy>=2.0,<3` (locked at 2.1.6). |
| `domain/`, `application/` | Never import SQLAlchemy (import-linter forbids it). |

## How it works underneath

**Engine and pool.** `create_engine(url, ...)` makes an **engine**: the starting point for all database access. It holds a **connection pool**, a small set of open connections that are lent out and returned, so requests do not pay to connect each time. `pool_size=5` keeps up to 5 connections; `pool_pre_ping=True` tests a pooled connection with a trivial query before lending it, replacing it if it died. The **URL** `postgresql+psycopg://user:password@host:port/database` names the database kind and the driver. `connect_args` are passed to the driver's `connect` (here a connect timeout and server options).

**Mapped classes.** A class that inherits from a `DeclarativeBase` subclass describes a table: `__tablename__ = "orders"`, and each column is `name: Mapped[type] = mapped_column(...)`. `Mapped[int]` is a type hint that says what Python type the column holds (and `Mapped[str | None]` allows NULL). `ForeignKey("customers.id")` declares a link. `relationship()` declares the Python-side link from an order to its customer.

**Session.** A `Session` is the conversation with the database: it borrows a connection from the pool, runs statements, remembers the objects it loaded, and gives the connection back when closed. `sessionmaker(engine, expire_on_commit=False)` is a factory for sessions; `with factory() as session:` closes the session at the end of the block. `expire_on_commit=False` keeps loaded objects usable after a commit.

**Building queries (2.0 style).** `select(Order)` selects whole objects; `select(Order.id, Order.status)` selects columns (rows come back as named tuples). Methods chain: `.where(condition)`, `.order_by(Order.created_at.desc(), Order.id.desc())`, `.offset(n)`, `.limit(n)`. `session.scalars(statement)` returns the first column of each row (for `select(Order)`, the objects); `session.execute(statement)` returns whole rows. `tuple_(a, b) < tuple_(x, y)` is SQL's row comparison `(a, b) < (x, y)`. `column == any_(array_parameter)` is SQL `column = ANY($1)`.

**Lazy loading and the N+1 problem.** By default (`lazy="select"`), a `relationship()` attribute is not loaded with its parent. The first time you read `order.customer`, SQLAlchemy sends a separate `SELECT` for that customer. Loading 20 orders and reading each customer sends 1 query for the orders and up to 20 for the customers: the **N+1 problem**. The fixes are to load the related rows together (eager loading with a join or `IN`) or to fetch them yourself in one extra query.

**Events.** `event.listen(engine, "before_cursor_execute", function)` calls your function before every statement the engine sends; tests use it to count statements.

## Walkthrough of this repository's use

### The mapping

`src/busy_listing/infrastructure/orm.py`, lines 1 to 43:

```python
"""Adapter: the ORM mapping and the SQLAlchemy engine. `Order.customer` is lazy on purpose (the planted N+1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, ForeignKey, Numeric, Text, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .settings import PostgresSettings


class Base(DeclarativeBase):
    """Declarative base of the lab's tables."""


class Customer(Base):
    """A customer (table `customers`)."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column()


class Order(Base):
    """An order (table `orders`). Touching `order.customer` runs one SELECT per order."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship()

```

- Imports: `Engine`, `ForeignKey`, `Numeric`, `Text`, `create_engine` from `sqlalchemy`; `URL` to build the connection address safely; `DeclarativeBase`, `Mapped`, `mapped_column`, `relationship` from `sqlalchemy.orm`; and `PostgresSettings` from the settings module.
- `class Base(DeclarativeBase)`: the common parent of the mapped classes (it keeps the table registry).
- `class Customer(Base)`: `__tablename__ = "customers"` names the table. `id: Mapped[int] = mapped_column(primary_key=True)` is an integer primary key. `name` and `email` are `Text`. `country_code: Mapped[str] = mapped_column()` takes its database type from the hint (text).
- `class Order(Base)` for `orders`: `id` (primary key), `customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))`, `status`, `total: Mapped[Decimal] = mapped_column(Numeric(10, 2))` (an exact decimal, as in the table), `created_at: Mapped[datetime]` and `note: Mapped[str | None]` (may be NULL).
- `customer: Mapped[Customer] = relationship()` is the planted problem. It declares that an order has a customer, found through the foreign key. There is no `lazy=` argument, so the default `lazy="select"` applies: the customer is loaded by a separate `SELECT` the first time `order.customer` is read. The class docstring says so: "Touching `order.customer` runs one SELECT per order."

### The engine

`src/busy_listing/infrastructure/orm.py`, lines 45 to 66:

```python
def create_lab_engine(settings: PostgresSettings, pool_size: int) -> Engine:
    """An engine with a connect timeout, a statement timeout and parallel query off for plans that read the same."""
    url = URL.create(
        "postgresql+psycopg",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
    )
    return create_engine(
        url,
        pool_size=pool_size,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "options": (
                f"-c statement_timeout={settings.statement_timeout_ms} "
                f"-c max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather}"
            ),
        },
    )
```

`URL.create("postgresql+psycopg", username=..., password=..., host=..., port=..., database=...)` builds the address as an object, so a password with special characters needs no escaping. `postgresql+psycopg` means PostgreSQL through the psycopg 3 driver. `create_engine(url, pool_size=pool_size, pool_pre_ping=True, connect_args={...})`: the pool holds up to `DB_POOL_SIZE` (5) connections; each is tested before use; and `connect_args` carries `connect_timeout` and the same `options` string as the psycopg note (`statement_timeout` and `max_parallel_workers_per_gather=0`), so ORM sessions get the same server settings as the other connections.

### The three listings

`src/busy_listing/infrastructure/sqlalchemy_orders.py`, lines 1 to 31:

```python
"""Adapter: the three listings with SQLAlchemy. Implements `OrderRepository`."""

from __future__ import annotations

from sqlalchemy import Engine, Integer, any_, bindparam, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from ..domain.cursor import Cursor
from ..domain.listing import PAGE_SIZE, ListedOrder, Page
from .orm import Customer, Order

_NEWEST_FIRST = (Order.created_at.desc(), Order.id.desc())


class SqlAlchemyOrders:
    """Reads pages of orders; one session per call, closed afterwards."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def naive_page(self, page: int) -> Page:
        """Entities by OFFSET; `order.customer.name` loads each customer lazily: one statement per order."""
        with self._sessions() as session:
            orders = session.scalars(select(Order).order_by(*_NEWEST_FIRST).offset(page * PAGE_SIZE).limit(PAGE_SIZE))
            return Page(
                tuple(
                    ListedOrder(o.id, o.customer_id, o.customer.name, o.status, str(o.total), o.created_at)
                    for o in orders.all()
                )
            )
```

- `_NEWEST_FIRST = (Order.created_at.desc(), Order.id.desc())` is the ordering used everywhere: newest first, ties broken by id (SQL: `ORDER BY created_at DESC, id DESC`).
- `self._sessions = sessionmaker(engine, expire_on_commit=False)` is the session factory.
- `naive_page(page)`: `with self._sessions() as session:` opens a session. `select(Order).order_by(*_NEWEST_FIRST).offset(page * PAGE_SIZE).limit(PAGE_SIZE)` is `SELECT ... FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET page*20` (`*` unpacks the tuple into arguments). `session.scalars(...)` yields `Order` objects. The generator `ListedOrder(o.id, o.customer_id, o.customer.name, ...)` reads `o.customer.name`: for each order, a lazy load, one `SELECT ... FROM customers WHERE customers.id = $1`. Twenty orders, twenty-one statements. Because `tuple(...)` consumes the generator inside the `with`, the session is still open when the lazy loads happen.

`src/busy_listing/infrastructure/sqlalchemy_orders.py`, lines 33 to 45:

```python
    def batched_page(self, page: int) -> Page:
        """The same OFFSET query, then the page's customers in one `id = ANY($1)` query."""
        with self._sessions() as session:
            orders = session.scalars(
                select(Order).order_by(*_NEWEST_FIRST).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
            ).all()
            names = self._customer_names(session, [o.customer_id for o in orders])
            return Page(
                tuple(
                    ListedOrder(o.id, o.customer_id, names[o.customer_id], o.status, str(o.total), o.created_at)
                    for o in orders
                )
            )
```

- `batched_page(page)` runs the same orders query with `.all()` (a list), then one query for all the customers: `names = self._customer_names(session, [o.customer_id for o in orders])`, and uses the dictionary `names[o.customer_id]`. Two statements per page.

`src/busy_listing/infrastructure/sqlalchemy_orders.py`, lines 47 to 69:

```python
    def keyset_page(self, after: Cursor | None, page_size: int = PAGE_SIZE) -> Page:
        """Rows strictly after the bookmark; only the listed columns, so a covering index can answer alone."""
        statement = select(Order.id, Order.customer_id, Order.status, Order.total, Order.created_at)
        if after is not None:
            statement = statement.where(tuple_(Order.created_at, Order.id) < tuple_(after.created_at, after.order_id))
        with self._sessions() as session:
            rows = session.execute(statement.order_by(*_NEWEST_FIRST).limit(page_size)).all()
            names = self._customer_names(session, [row.customer_id for row in rows])
            listing = tuple(
                ListedOrder(r.id, r.customer_id, names[r.customer_id], r.status, str(r.total), r.created_at)
                for r in rows
            )
            last = rows[-1] if len(rows) == page_size else None
            return Page(listing, Cursor(last.created_at, last.id) if last else None)

    @staticmethod
    def _customer_names(session: Session, customer_ids: list[int]) -> dict[int, str]:
        """One query for every customer on the page: `id = ANY($1)` keeps a single statement shape for any page."""
        ids = bindparam("ids", sorted(set(customer_ids)), type_=ARRAY(Integer))
        return {
            row.id: row.name
            for row in session.execute(select(Customer.id, Customer.name).where(Customer.id == any_(ids)))
        }
```

- `keyset_page(after, page_size)`: `select(Order.id, Order.customer_id, Order.status, Order.total, Order.created_at)` loads only the five columns the listing shows (no `note`, no objects). If `after` (a `Cursor`) is given, `.where(tuple_(Order.created_at, Order.id) < tuple_(after.created_at, after.order_id))` adds `WHERE (created_at, id) < ($1, $2)`: the rows after the bookmark in the newest-first order. `.limit(page_size)` and no `OFFSET`. `session.execute(...).all()` returns rows with named columns (`row.id`). The next cursor is built from the last row only if the page is full (`len(rows) == page_size`), otherwise `None`.
- `_customer_names(session, customer_ids)` is a `@staticmethod` (a method that does not use `self`). `bindparam("ids", sorted(set(customer_ids)), type_=ARRAY(Integer))` makes one array parameter holding the distinct customer ids, sorted; `Customer.id == any_(ids)` is SQL `customers.id = ANY($1)`. The same SQL text is used for any page, so `pg_stat_statements` counts it as one statement. The dictionary comprehension builds `{customer id: name}`.

### The statement counter in the tests

`tests/integration/conftest.py`, lines 54 to 74:

```python
class StatementCounter:
    """Every statement the engine sends to PostgreSQL while a test runs."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)


@pytest.fixture
def statement_counter(engine: Engine) -> Iterator[StatementCounter]:
    counter = StatementCounter()

    def record(_connection: object, _cursor: object, statement: str, *_rest: object) -> None:
        counter.statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield counter
    event.remove(engine, "before_cursor_execute", record)
```

`event.listen(engine, "before_cursor_execute", record)` calls `record` before every statement SQLAlchemy sends; the fixture collects the statement texts and removes the listener afterwards. `test_step2_...` asserts that `naive_page` sends at least 15 statements and the fixed versions at most 2.

## Try it yourself

(After `make up db`; load your `.env` with `set -a; . ./.env; set +a`.)

1. `.venv/bin/python -c "import sqlalchemy; print(sqlalchemy.__version__)"` prints `2.1.6`.
2. Count the statements of the naive version: 
   `.venv/bin/python -c "
from sqlalchemy import event
from busy_listing.infrastructure.orm import create_lab_engine
from busy_listing.infrastructure.settings import Settings
from busy_listing.infrastructure.sqlalchemy_orders import SqlAlchemyOrders
s = Settings.from_env(); e = create_lab_engine(s.postgres, 5); seen = []
event.listen(e, 'before_cursor_execute', lambda c, cur, stmt, *a: seen.append(stmt))
SqlAlchemyOrders(e).naive_page(0); print(len(seen))
seen.clear(); SqlAlchemyOrders(e).batched_page(0); print(len(seen))
seen.clear(); SqlAlchemyOrders(e).keyset_page(None); print(len(seen))"`
   prints `21`, then `2`, then `2`. (The integration test asserts at least 15 for the naive version and at most 2 for the fixed ones.)
3. `.venv/bin/python -m pytest tests/integration -q -k step2` runs the two N+1 tests.
4. `make run` and then read the top of `sql/explain/results.md`: phase 1 shows 6,300 statements for 300 requests (21 per request), phases 2 to 4 show 600.

## Mistakes people make

- Reading a lazy relationship in a loop (N+1).
- Keeping a session open too long, or sharing one session between threads.
- Using `SELECT *`-style whole-object loads when a listing needs three columns.
- Forgetting that a lazy attribute cannot load after the session is closed.
- Building SQL strings by hand next to the ORM.

**How this repository avoids them.** The lazy relationship is kept on purpose in one place (the naive method) and documented as the planted problem; the other two methods never touch it; sessions are short and always closed; the engine has a pool, a ping, timeouts and the same server settings; and a test counts statements so the N+1 cannot come back unnoticed.

## Check yourself

1. What is the N+1 problem? *One query for N parent rows plus one query per row for a lazily loaded related object.*
2. What does a connection pool save? *The cost of opening a new database connection for each request.*
3. What does `Mapped[str | None]` say? *The column holds text and may be NULL.*
4. What does `session.scalars(select(Order))` return? *The `Order` objects, one per row.*
5. What does `expire_on_commit=False` do? *Loaded objects keep their values after a commit instead of being marked stale.*

## Further reading

- SQLAlchemy 2.1 documentation: https://docs.sqlalchemy.org/en/latest/ — "ORM Quick Start", "Relationship Loading Techniques", "Engine Configuration", "Session Basics".

# Python dataclasses

## What it is

A **dataclass** is a Python class whose main job is to hold a few named values. You list the fields with their types, add the decorator `@dataclass`, and Python writes the boring methods for you: the one that sets the fields when you create an object (`__init__`), the one that prints it (`__repr__`), and the one that compares two objects (`__eq__`). The decorator lives in the standard library module `dataclasses`.

## Why this repository uses it

The code passes small bundles of facts between layers: a bookmark, a page of orders, a request for a page, the statistics of a statement, the timings of a load, a settings object. Dataclasses make each one a named, read-only, self-describing value with almost no code.

## Where it appears

| File | Dataclasses |
|---|---|
| `domain/cursor.py` | `Cursor` |
| `domain/listing.py` | `ListedOrder`, `Page`, `ListingRequest` |
| `domain/statements.py` | `StatementStat` |
| `domain/load.py` | `LoadTimings` |
| `domain/lesson.py` | `Phase` |
| `domain/plan.py` | `PlanSummary` |
| `domain/host.py` | `HostLoad` |
| `application/health.py` | `ProbeResult`, `HealthReport` |
| `application/replay.py` | `PhaseResult`, `LessonResult` |
| `infrastructure/settings.py` | `PostgresSettings`, `AppSettings`, `Settings` |

## How it works underneath

```python
@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float
```

- `x: float` is a **field declaration**: a name, a colon and a type hint. It is not an assignment.
- **Creating an object.** `Point(1.0, 2.0)` or `Point(x=1.0, y=2.0)`. The generated `__init__` assigns the values to `self.x` and `self.y`.
- **`repr`.** `print(Point(1.0, 2.0))` shows `Point(x=1.0, y=2.0)`.
- **`eq`.** Two objects with equal fields are equal (`==`).
- **`frozen=True`.** The object is read-only after creation; `p.x = 3` raises `FrozenInstanceError`. A frozen dataclass is also **hashable**, so it can be a dictionary key or set member. Immutable values are easier to reason about, and safe to share between threads.
- **`slots=True`.** Python normally stores an object's attributes in a hidden dictionary. With slots it reserves fixed places instead: less memory, and a typo like `p.z = 1` is an error instead of silently adding an attribute.
- **Defaults.** `limit: int = 5` makes a field optional. Fields with defaults must come after fields without. A mutable default such as a list must use `field(default_factory=list)`.
- **`field(repr=False)`** hides one field from the printed form: used for secrets, so a password is never printed by accident.
- **Methods and properties** can be added like in any class.
- **Order.** The order of the fields is the order of the positional arguments.

A dataclass is not checked at run time: `Point("a", "b")` is accepted. The type hints are for tools like mypy and for readers.

## Walkthrough of this repository's use

All sixteen use the same decorator, `@dataclass(frozen=True, slots=True)`: read-only and memory-lean.

`src/busy_listing/domain/plan.py`, lines 25 to 34:

```python
@dataclass(frozen=True, slots=True)
class PlanSummary:
    """One executed plan, reduced to the numbers the lesson compares."""

    execution_ms: float
    pages: int
    node_types: tuple[str, ...]
    index_names: tuple[str, ...]
    rows_removed_by_filter: int
    heap_fetches: int | None
```

`PlanSummary` has six fields. The generated constructor takes them in this order: `execution_ms, pages, node_types, index_names, rows_removed_by_filter, heap_fetches`. `parse_text_plan` calls it with keyword arguments, which makes the order irrelevant. `heap_fetches: int | None` can be `None`.

`src/busy_listing/domain/cursor.py`, lines 18 to 23:

```python
@dataclass(frozen=True, slots=True)
class Cursor:
    """A position in the newest-first ordering: rows strictly after this one come next."""

    created_at: datetime
    order_id: int
```

`Cursor` is the bookmark of keyset paging: when the last row was created and its id. It is frozen, so a bookmark cannot change after a client has been given its encoded form, and, because it is frozen and compares by value, `Cursor.decode(cursor.encode()) == cursor` is a meaningful test.

`src/busy_listing/domain/listing.py`, lines 31 to 68:

```python
@dataclass(frozen=True, slots=True)
class ListedOrder:
    """One row of the listing: an order and its customer's name."""

    id: int
    customer_id: int
    customer_name: str
    status: str
    total: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Page:
    """One page of orders, newest first, and the cursor of the next page when keyset paging."""

    orders: tuple[ListedOrder, ...]
    next_cursor: Cursor | None = None


@dataclass(frozen=True, slots=True)
class ListingRequest:
    """A validated request for a page. Build it with `ListingRequest.of`."""

    strategy: Strategy
    page: int
    cursor: Cursor | None

    @classmethod
    def of(cls, strategy: Strategy, page: int = 0, cursor: Cursor | None = None) -> ListingRequest:
        """Check the combination of arguments the strategy allows."""
        if page < 0:
            raise InvalidPageError(f"page must be 0 or more, got {page}")
        if strategy is Strategy.KEYSET and page:
            raise PageNumberNotSupportedError(
                "keyset paging has no page numbers: pass the cursor from the previous page"
            )
        return cls(strategy, page, cursor)
```

`ListedOrder` is one row of the listing; `Page` has `next_cursor: Cursor | None = None`, a field with a default (so it comes last); `ListingRequest` is a validated request, built with the class method `of` (so a request that exists is valid).

`src/busy_listing/domain/statements.py`, lines 23 to 38:

```python
@dataclass(frozen=True, slots=True)
class StatementStat:
    """Calls and total execution time of one statement text."""

    query: str
    calls: int
    total_ms: float

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0

    @property
    def short(self) -> str:
        """The statement on one line, for tables."""
        return " ".join(self.query.split())
```

`StatementStat` has three fields (the statement text, the number of calls, the total milliseconds) and two read-only properties computed from them.

`src/busy_listing/application/replay.py`, lines 18 to 26:

```python
@dataclass(frozen=True, slots=True)
class PhaseResult:
    """What one run of the load cost, and which statements it was made of."""

    label: str
    by_time: tuple[StatementStat, ...]
    by_calls: tuple[StatementStat, ...]
    database_ms: float
    statements: int
```

`PhaseResult` is what one run of the load cost (label, the two top lists as tuples, database time, number of statements, wall-clock seconds, a dictionary of medians per page). `LessonResult` holds the four phase results and the plans; its last field has a default, `host_load: HostLoad | None = None`, and must come last because fields with defaults follow fields without.

`src/busy_listing/infrastructure/settings.py`, lines 41 to 61:

```python
@dataclass(frozen=True, slots=True)
class PostgresSettings:
    """The PostgreSQL part of the configuration; the password is never printed."""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    connect_timeout_seconds: int
    statement_timeout_ms: int
    max_parallel_workers_per_gather: int


@dataclass(frozen=True, slots=True)
class AppSettings:
    """The listing service and its load."""

    host: str
    port: int
    default_strategy: Strategy
```

`PostgresSettings` has `password: str = field(repr=False)`. (`AppSettings` holds the service's own settings: host, port, default strategy, number of load requests, HTTP timeout and pool size.) `field(...)` with only `repr=False` and no default means: a required field, hidden from the printed form. So `print(settings.postgres)` never shows the password. `Settings` holds a `PostgresSettings`, a `Path` and the log level; it also has a `@classmethod` (`from_env`) that builds an instance from environment variables (the environment note).

`src/busy_listing/domain/host.py`, lines 8 to 18:

```python
@dataclass(frozen=True, slots=True)
class HostLoad:
    """The 1-minute load average and the CPU count at the start of a measurement."""

    load_average: float
    cpus: int

    @property
    def loaded(self) -> bool:
        """True when more than half a runnable task per CPU was waiting: timings are inflated."""
        return self.load_average > self.cpus / 2
```

`HostLoad` shows a dataclass with a property. `loaded` is not a field; it is computed from two fields every time it is read.

## Try it yourself

1. `.venv/bin/python -c "from busy_listing.infrastructure.settings import PostgresSettings as P; print(P('h',1,'d','u','SECRET',5,1,0))"` prints the object without the word `SECRET`: `PostgresSettings(host='h', port=1, database='d', user='u', connect_timeout_seconds=5, statement_timeout_ms=1, max_parallel_workers_per_gather=0)`.
2. `.venv/bin/python -c "from busy_listing.domain.host import HostLoad as H; h=H(1.0,4); h.cpus=8"` ends with `dataclasses.FrozenInstanceError: cannot assign to field 'cpus'`.
3. `.venv/bin/python -c "from busy_listing.domain.host import HostLoad as H; print(H(1.0,4)==H(1.0,4), hash(H(1.0,4))==hash(H(1.0,4)))"` prints `True True`.
4. `.venv/bin/python -c "from busy_listing.domain.host import HostLoad as H; h=H(1.0,4); h.extra=1"` is refused with a `TypeError` whose text starts `super(type, obj): obj (instance of HostLoad) is not an instance or subtype of type (HostLoad)`. That odd message is how Python 3.13 reports an unknown attribute on an object that is both frozen and slotted; the point is that the new attribute is not accepted.

## Mistakes people make

- Mutable defaults (`items: list = []`): Python refuses; use `field(default_factory=list)`.
- Putting a field with a default before one without.
- Assuming type hints validate input.
- Making an object frozen and then trying to change it: create a new one with `dataclasses.replace(obj, field=new_value)`.
- Printing an object that holds a password.

**How this repository avoids them.** All dataclasses are frozen. No field has a mutable default. The password field is hidden from `repr`. mypy checks the types that the dataclasses declare.

## Check yourself

1. What does `@dataclass` write for you? *`__init__`, `__repr__` and `__eq__` (and more, depending on the options).*
2. What does `frozen=True` prevent? *Changing a field after the object is created.*
3. What does `slots=True` do? *It stores attributes in fixed slots: less memory and no accidental new attributes.*
4. What is `field(repr=False)` for? *Hiding a field from the printed form of the object, for example a password.*
5. Do dataclasses check types when you create an object? *No; the type hints are only for tools and readers.*

## Further reading

- `dataclasses` module (Python 3.13): https://docs.python.org/3.13/library/dataclasses.html

# Python

## What it is

**Python** is a programming language: you write instructions in a text file (a `.py` file), and a program called the **interpreter** reads the file and carries the instructions out one after another. It is known for being readable, and it comes with a large **standard library** of ready-made tools (files, text, dates, networking). Python is **dynamically typed** (a name can hold any kind of value, checked when the line runs), but it supports optional **type hints** that other tools check beforehand (see the typing note).

## Why this repository uses it

The listing service, the ORM mapping, the load script and the replay are all Python, and so are the tests. The code is arranged in four layers; this note walks through `domain`, `application` and the shared start-up code of `interfaces`. The other modules are explained where their main technology is: `interfaces/http_app.py` and `service.py` in the FastAPI, uvicorn and HTTP notes, `infrastructure/orm.py` and `sqlalchemy_orders.py` in the SQLAlchemy note, `infrastructure/postgres.py`, `lab_indexes.py`, `pg_stat_statements.py` and `health_probes.py` in the psycopg and pg_stat_statements notes, `http_load.py` in the requests note, `settings.py` in the environment-variables note, `logging.py` in the logging note, `shutdown.py` and the `*_cli.py` files in the command-line note, and `artifacts.py`, `retry.py` and `sql_script.py` in the standard-library note.

## Where it appears

| Folder | What is there |
|---|---|
| `src/busy_listing/domain/` | Pure rules: the cursor, the listing request and its strategies, statement ranking, load timings, plan parsing, host load, the lesson's phases, errors. No input or output. |
| `src/busy_listing/application/` | The use cases (list one page, replay the lesson, health), the report, and the ports they need. |
| `src/busy_listing/infrastructure/` | The code that touches the outside world. |
| `src/busy_listing/interfaces/` | The web application and the commands. |
| `tests/` | Unit, integration and end-to-end tests (pytest note). |

## How it works underneath

**Running.** `python file.py` starts the interpreter as a process, which compiles the file into **bytecode** (a compact internal form), then runs it. `python -m package.module` runs a module found through the import system; the code under `if __name__ == "__main__":` runs only when the file is started this way, not when it is imported.

**Names and values.** `x = 5` makes the name `x` refer to the value 5. Values have types: `int` (whole numbers), `float` (numbers with a fraction), `str` (text), `bool` (`True` or `False`), `None` (no value), `list` (`[1, 2]`, changeable), `tuple` (`(1, 2)`, fixed), `dict` (`{"a": 1}`, name-to-value map), `set` (`{1, 2}`, unique items).

**Blocks are indented.** After a line ending in `:` (`if`, `for`, `def`, `class`, `try`, `with`), the following lines indented four spaces are its body.

**Statements you will meet.**

- `import module` and `from module import name` load code from another file. A leading dot (`from .plan import X`, `from ..domain import Y`) is a **relative import**: `.` means this package, `..` the parent package.
- `def name(parameters) -> result:` defines a **function**. `*` in the parameter list means "everything after this must be passed by name" (keyword-only). A default value (`attempts: int = 5`) makes an argument optional. `return value` ends the function with a result.
- `class Name:` defines a **class**: a recipe for objects bundling data and functions (**methods**). `self` is the object a method works on. `__init__` runs when an object is created. A class in parentheses (`class LabError(Exception)`) **inherits** from another class. A leading underscore (`_name`) marks something as private by convention.
- `@decorator` above a function or class passes it through another function that wraps or changes it. `@property` turns a method into something read like an attribute (`obj.speedup`); `@classmethod` makes a method that works on the class, not an object.
- `if` / `elif` / `else`, `for item in things:`, `while`, `break`, `continue`.
- `try:` / `except ErrorType as error:` / `finally:` handle errors. `raise Error("text")` creates one. `raise X from y` records that `y` was the cause. `finally` always runs.
- `with something as name:` runs a block with a **context manager** that sets up and always cleans up (a file closed, a connection closed).
- `assert condition, "message"` raises `AssertionError` if the condition is false.
- `yield` makes a function a **generator**: it produces values one at a time when asked. `yield from other` hands over the values of another generator.
- `lambda x: expression` is a one-line anonymous function.

**Expressions.** F-strings, `f"{value:.3f}"`, put values into text; after the colon comes a **format**: `.3f` is three digits after the point, `,` adds thousands separators, `8.1f` means width 8 with one decimal. A **comprehension** builds a collection in one line: `[x * 2 for x in items if x > 0]` (list), `{k: v for ...}` (dict), `(x for x in ...)` (generator). `a if condition else b` picks one. `*` before a collection inside brackets spreads its items: `[*first, *second]`. Slicing `items[1:5]` takes a range; `text[:60]` the first 60 characters.

**Truthiness.** `if items:` is true when the list is not empty; empty text, `0` and `None` are false.

**Errors.** An uncaught error ends the program with a **traceback**, a list of the lines that led to it, and exit code 1.

**Modules and packages.** One `.py` file is a module; a folder with `__init__.py` is a package. `__name__` is the module's name, or `"__main__"` when it was started directly. `__file__` is its path.

## Walkthrough of this repository's use

### `domain/errors.py`

`src/busy_listing/domain/errors.py`, lines 1 to 29:

```python
"""Named errors of the listing. Each says what the caller got wrong, in the caller's terms."""


class LabError(Exception):
    """Base class of every error this package raises on purpose."""


class InvalidCursorError(LabError):
    """A keyset cursor that this service did not issue, or that was damaged on the way."""


class UnknownStrategyError(LabError):
    """A listing strategy other than naive, batched or keyset."""


class PageNumberNotSupportedError(LabError):
    """Keyset paging has no page numbers: the client passes the cursor from the previous page."""


class InvalidPageError(LabError):
    """A negative page number."""


class LessonInterruptedError(LabError):
    """The replay was asked to stop (SIGINT or SIGTERM) between two phases."""


class PlanParseError(LabError):
    """A query plan did not have the lines or fields the lesson reads."""
```

Line 1 is a **docstring**: a text in triple quotes as the first statement of a module, class or function; tools show it as documentation. `class LabError(Exception):` defines a new kind of error that **inherits** from Python's built-in `Exception`; the body is only a docstring, which is a complete class. The other classes inherit from `LabError`, so one `except LabError` catches every error this package raises on purpose, and the web layer can turn that one family into HTTP 400 answers (FastAPI note). Each name ends in `Error` (ruff rule `N818`). Each docstring says what the *caller* got wrong, because these messages reach users.

### `domain/host.py`

`src/busy_listing/domain/host.py`, lines 1 to 27:

```python
"""How busy the machine was while something was measured, so a reader can discount the milliseconds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostLoad:
    """The 1-minute load average and the CPU count at the start of a measurement."""

    load_average: float
    cpus: int

    @property
    def loaded(self) -> bool:
        """True when more than half a runnable task per CPU was waiting: timings are inflated."""
        return self.load_average > self.cpus / 2

    def note(self) -> str:
        """One sentence for the results file."""
        if self.loaded:
            return (
                f"Measured on a loaded machine (load average {self.load_average:.1f} on {self.cpus} CPUs); rerun "
                "`make run` on a quiet machine for clean figures. The ratios survive load better than the milliseconds."
            )
        return f"Measured at load average {self.load_average:.1f} on {self.cpus} CPUs."
```

- Line 3 `from __future__ import annotations` makes type hints be stored as text and evaluated lazily (typing note).
- Line 5 imports `dataclass`; lines 8 to 13 define a class with two fields; the dataclass note explains what the decorator generates.
- `@property def loaded(self) -> bool:` is read as `host_load.loaded`, without parentheses. It compares the load average with half the number of CPUs; `>` gives a `bool`.
- `note` returns text. `if self.loaded:` chooses the branch. Inside the `return (...)`, two string literals side by side are joined into one by Python. The first is an **f-string** (prefix `f`): `{self.load_average:.1f}` inserts the number with one decimal, `{self.cpus}` inserts the CPU count. The backticks inside the text are just characters (they make Markdown show code).
- The second `return` is the quiet-machine case.


### `domain/listing.py`

`src/busy_listing/domain/listing.py`, lines 1 to 68:

```python
"""What the listing page shows and how a client asks for it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .cursor import Cursor
from .errors import InvalidPageError, PageNumberNotSupportedError, UnknownStrategyError

PAGE_SIZE = 20


class Strategy(StrEnum):
    """The lesson's three versions of the listing."""

    NAIVE = "naive"  # OFFSET paging, one lazy customer query per order
    BATCHED = "batched"  # the same OFFSET query, customers fetched together
    KEYSET = "keyset"  # rows after a bookmark, only the listed columns

    @classmethod
    def parse(cls, name: str) -> Strategy:
        """The strategy called `name`; raises `UnknownStrategyError` for anything else."""
        try:
            return cls(name)
        except ValueError as error:
            raise UnknownStrategyError(f"unknown strategy {name!r}; use naive, batched or keyset") from error


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

- `PAGE_SIZE = 20`: a constant (capital letters by convention).
- `class Strategy(StrEnum)`: an **enumeration**, a fixed set of named values. `StrEnum` makes each member also a string: `Strategy.NAIVE == "naive"` is true. The three members are written `NAME = "value"`, and the trailing `# ...` comments say what each strategy does.
- `@classmethod def parse(cls, name: str) -> Strategy`: `cls` is the class itself. `cls(name)` looks a member up by value (`Strategy("keyset")` gives `Strategy.KEYSET`) and raises `ValueError` for an unknown value; the `try`/`except ValueError as error: raise UnknownStrategyError(...) from error` turns that into the package's own error whose message lists the choices. The `!r` inside the f-string shows the value with quotes (`'fast'`).
- `ListedOrder`, `Page` and `ListingRequest` are frozen dataclasses (dataclasses note). `Page.next_cursor: Cursor | None = None` has a default, so it must come last.
- `ListingRequest.of(strategy, page=0, cursor=None)` is a **named constructor** that validates: a negative page raises `InvalidPageError`; `strategy is Strategy.KEYSET and page` (the identity test `is` is the right way to compare enum members; `page` is true for any non-zero number) raises `PageNumberNotSupportedError`. If everything is fine it returns `cls(strategy, page, cursor)`. A request that exists is therefore always valid.

### `domain/cursor.py`

`src/busy_listing/domain/cursor.py`, lines 1 to 38:

```python
"""Opaque keyset cursors: the (created_at, id) of the last row a client received.

The client treats the token as a string and passes it back. Base64 hides the shape, it does not protect it:
a real service would sign the token so a client cannot forge one.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidCursorError


@dataclass(frozen=True, slots=True)
class Cursor:
    """A position in the newest-first ordering: rows strictly after this one come next."""

    created_at: datetime
    order_id: int

    def encode(self) -> str:
        """The opaque token handed to the client."""
        payload = json.dumps({"t": self.created_at.isoformat(), "i": self.order_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        """Read a token back; raises `InvalidCursorError` for anything this service did not issue."""
        try:
            padded = token + "=" * (-len(token) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return cls(datetime.fromisoformat(payload["t"]), int(payload["i"]))
        except (binascii.Error, ValueError, KeyError, TypeError) as error:
            raise InvalidCursorError("the cursor is not one this service issued") from error
```

The cursor is the "bookmark" of keyset paging: the `created_at` and `id` of the last row the client received.

- `encode(self) -> str` builds a dictionary `{"t": ..., "i": ...}` (short keys), turns it into compact JSON text with `json.dumps(..., separators=(",", ":"))` (no spaces), converts the text to bytes (`.encode()`), encodes the bytes as URL-safe base64 (`base64.urlsafe_b64encode`: only letters, digits, `-` and `_`), converts back to text (`.decode()`) and strips the padding `=` signs (`.rstrip("=")`) so the token has no characters that need escaping in a URL.
- `decode(cls, token)` reverses it. `padded = token + "=" * (-len(token) % 4)` adds back the padding that base64 needs (its length must be a multiple of 4; `-len(token) % 4` is the number of missing characters). `json.loads(base64.urlsafe_b64decode(padded))` decodes and parses. `cls(datetime.fromisoformat(payload["t"]), int(payload["i"]))` rebuilds the cursor. Anything that goes wrong (bad base64: `binascii.Error`; bad JSON or time: `ValueError`; a missing key: `KeyError`; a wrong type: `TypeError`) is caught in one `except` with a tuple of error classes and re-raised as `InvalidCursorError` ("the cursor is not one this service issued") with the original as the cause.
- The docstring warns that base64 only hides the shape; a real service would sign the token so it cannot be forged.

### `domain/statements.py`

`src/busy_listing/domain/statements.py`, lines 1 to 65:

```python
"""Statements as `pg_stat_statements` reports them, and how the lesson ranks them.

The view keys its rows by a query id that includes parameter types, and the driver sends an integer parameter as
`int2`, `int4` or `int8` depending on its value, so one SQL text can appear under several ids. Ranking the rows as
they are would split one statement's calls and understate it, so rows with the same text are added together.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class RankBy(StrEnum):
    """The two rankings the lesson reads: where the database spent its time, and what is asked most often."""

    TOTAL_TIME = "total_exec_time"
    CALLS = "calls"


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


def total_time_ms(rows: Sequence[StatementStat]) -> float:
    """All the database time the statements account for."""
    return sum(row.total_ms for row in rows)


def total_calls(rows: Sequence[StatementStat]) -> int:
    """All the statements that ran."""
    return sum(row.calls for row in rows)
```

(The pg_stat_statements note explains why rows are merged.)

- `class RankBy(StrEnum)` with two members whose values are the view's column names.
- `StatementStat` is a frozen dataclass with two **properties**: `mean_ms` divides total by calls (`x / y if y else 0.0` avoids dividing by zero) and `short` joins the words of the query with single spaces (`" ".join(self.query.split())`: `split()` with no argument splits on any run of blanks and line breaks), so a multi-line statement fits in one table cell.
- `merge_by_text(rows)`: `calls: dict[str, int] = defaultdict(int)` is a dictionary that returns 0 for a missing key (and `defaultdict(float)` 0.0). The loop adds each row's numbers under its query text. The result is a list comprehension that builds one `StatementStat` per distinct text.
- `rank(rows, by, limit=10)`: `sorted(merged, key=key, reverse=True)[:limit]`; `key` is a function chosen with a conditional expression of two `lambda`s; `[:limit]` slices the first `limit` items. Python's sort is stable, so ties keep their order.
- `total_time_ms` and `total_calls` use `sum(generator)`.

### `domain/load.py`

`src/busy_listing/domain/load.py`, lines 1 to 25:

```python
"""What the load script measured: how long each click took, per page."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass

#: For each page the load visits, the cursor that reaches it by keyset paging (None for the first page).
Bookmarks = Mapping[int, str | None]


@dataclass(frozen=True, slots=True)
class LoadTimings:
    """Every request of one load run as (page, milliseconds), and the wall-clock time of the run."""

    requests: tuple[tuple[int, float], ...]
    wall_seconds: float

    def median_by_page(self) -> dict[int, float]:
        """The median request time of each page that was visited."""
        by_page: dict[int, list[float]] = {}
        for page, milliseconds in self.requests:
            by_page.setdefault(page, []).append(milliseconds)
        return {page: statistics.median(values) for page, values in sorted(by_page.items())}
```

- `Bookmarks = Mapping[int, str | None]` is a **type alias**: a name for a type, used in annotations (page number to cursor token or `None`).
- `LoadTimings` holds every request as a `(page, milliseconds)` pair, and the total wall-clock time of the run.
- `median_by_page`: `by_page: dict[int, list[float]] = {}`, then `by_page.setdefault(page, []).append(milliseconds)` (`setdefault` returns the list for that page, creating an empty one the first time) collects times per page; the dictionary comprehension `{page: statistics.median(values) for page, values in sorted(by_page.items())}` computes the median of each, with pages in increasing order.

### `domain/lesson.py`

`src/busy_listing/domain/lesson.py`, lines 1 to 38:

```python
"""The lesson as data: the page sequence of the load, the phases and the plans read along the way."""

from __future__ import annotations

from dataclasses import dataclass

from .listing import Strategy

#: Pages the load visits, including genuinely deep ones. Keyset paging reaches them through bookmarks.
PAGES = (0, 1, 2, 50, 100, 5000, 10000)


@dataclass(frozen=True, slots=True)
class Phase:
    """One run of the same load: which version answers, and which index state the table is in."""

    label: str
    strategy: Strategy
    index_step: int  # 0: the ordering index only; 2: the covering index only (after both migrations)
    captures: tuple[str, ...] = ()


PHASES = (
    Phase("1 naive: offset paging, N+1 customer lookups", Strategy.NAIVE, 0),
    Phase("2 N+1 fixed: customers fetched in one query", Strategy.BATCHED, 0),
    Phase(
        "3 keyset paging on (created_at DESC, id DESC)", Strategy.KEYSET, 0, ("e2_keyset_page1", "e2_keyset_page10000")
    ),
    Phase(
        "4 keyset + covering index (expand, then contract)",
        Strategy.KEYSET,
        2,
        ("e3_keyset_page10000_covering",),
    ),
)

#: Plans read before any change: the cost of deep offsets.
OFFSET_PLANS = ("e1_offset_page1", "e1_offset_page100", "e1_offset_page10000")
```

- `PAGES = (0, 1, 2, 50, 100, 5000, 10000)` are the pages the load visits (counting from 0).
- `Phase` is a frozen dataclass: a label, the `Strategy` to use, `index_step` (0: only the original ordering index; 2: the covering index after both migrations) and the plans to capture (`captures: tuple[str, ...] = ()`).
- `PHASES` is a tuple of the four phases; the long `Phase(...)` calls are split over lines inside the brackets. `OFFSET_PLANS` names the three plans read before any change.

### `domain/plan.py` (the functions; the regular expressions are in their own note)

`src/busy_listing/domain/plan.py`, lines 1 to 14:

```python
"""What the lesson reads from a query plan: time, pages, node types, indexes and rows discarded.

Both plan formats are parsed here and nowhere else: the text of `EXPLAIN (ANALYZE, BUFFERS)` (what the
`.txt` files hold) and its JSON form (what the tests assert on). No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import PlanParseError
```

A multi-line docstring explains the module. Line 9 imports `re`, Python's regular-expression module. Line 10 imports abstract type names from `collections.abc`: `Iterable` (anything you can loop over), `Iterator` (something that produces values one by one), `Mapping` (dict-like, read-only), `Sequence` (list-like). Line 11 imports `dataclass`; line 12 `Any` ("any type"); line 14 the error `PlanParseError` from the sibling module.

`src/busy_listing/domain/plan.py`, lines 25 to 43:

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

    def has_node(self, node_type: str) -> bool:
        """True when any node of the plan has exactly this type, for example `Seq Scan` or `Sort`."""
        return node_type in self.node_types

    def uses_index(self, name: str) -> bool:
        """True when the plan reads the named index (index scan, index-only scan or bitmap index scan)."""
        return name in self.index_names

```

`PlanSummary` holds the numbers the lesson compares. `heap_fetches: int | None` means "a whole number or nothing" (`None`); it is `None` for plans without an index-only scan. The two methods answer yes/no questions: `node_type in self.node_types` tests whether a text is in the tuple. `has_node("Seq Scan")` is true if any step of the plan is a sequential scan.

`src/busy_listing/domain/plan.py`, lines 45 to 59:

```python
def parse_text_plan(lines: Sequence[str]) -> PlanSummary:
    """Summarize the text of an `EXPLAIN (ANALYZE, BUFFERS)` plan."""
    text = "\n".join(lines)
    execution = _EXECUTION.search(text)
    if execution is None:
        raise PlanParseError("no 'Execution Time' line: was the plan produced with ANALYZE?")
    heap_fetches = _HEAP_FETCHES.search(text)
    return PlanSummary(
        execution_ms=float(execution.group(1)),
        pages=pages_touched(lines),
        node_types=tuple(node.strip() for node in _NODE.findall(text)),
        index_names=tuple(dict.fromkeys(_INDEX.findall(text))),
        rows_removed_by_filter=sum(int(count) for count in _REMOVED.findall(text)),
        heap_fetches=int(heap_fetches.group(1)) if heap_fetches else None,
    )
```

`parse_text_plan(lines)` receives the plan as a sequence of text lines. `"\n".join(lines)` glues them into one text with line breaks (`"\n"` is the new-line character). `_EXECUTION.search(text)` looks for the first match of a regular expression and returns a match object, or `None`. `if execution is None: raise PlanParseError(...)` stops with a named error when the "Execution Time" line is missing. The `PlanSummary(...)` call fills the fields by name: `float(execution.group(1))` converts the matched digits to a number; `tuple(node.strip() for node in _NODE.findall(text))` is a **generator expression** inside `tuple(...)`: it takes every match of the node-type pattern, removes surrounding spaces with `.strip()` and collects them. `dict.fromkeys(...)` makes a dictionary whose keys are the items; since dictionary keys are unique and keep their order, wrapping a list in `dict.fromkeys` removes duplicates while keeping order. `sum(int(count) for count in _REMOVED.findall(text))` adds up all the "Rows Removed by Filter" numbers. `int(heap_fetches.group(1)) if heap_fetches else None` is a conditional expression.

`src/busy_listing/domain/plan.py`, lines 62 to 76:

```python
def pages_touched(lines: Iterable[str]) -> int:
    """Pages a plan touched: the top node's `Buffers: shared hit=.. read=..`, plus the pages read to send the rows.

    The second figure is the `Buffers` line after `Serialization:`, where out-of-line (TOAST) values are fetched.
    """
    total, after_serialization = 0, False
    for line in lines:
        if line.startswith("Serialization:"):
            after_serialization = True
            continue
        match = _BUFFERS.search(line)
        if match and (after_serialization or total == 0):
            total += sum(int(count) for count in _PAGE_COUNTS.findall(match.group(1)))
            after_serialization = False
    return total
```

`pages_touched` reads the "Buffers" lines. `total, after_serialization = 0, False` assigns two names at once (a tuple). The loop `for line in lines:` visits each line. `line.startswith("Serialization:")` is a text test; `continue` jumps to the next line. `match and (...)` uses **short-circuit** logic: if `match` is `None` the right side is not evaluated. `total += ...` adds to `total`. `match.group(1)` is the text captured by the first parenthesis of the pattern, and `_PAGE_COUNTS.findall(...)` returns every number after `hit=` or `read=`. So the function adds hits and reads of the top node, plus those of the line after `Serialization:`.

`src/busy_listing/domain/plan.py`, lines 79 to 100:

```python
def _json_nodes(node: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _json_nodes(child)


def parse_json_plan(document: Mapping[str, Any]) -> PlanSummary:
    """Summarize one element of the JSON that `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` returns."""
    try:
        root = document["Plan"]
        nodes = list(_json_nodes(root))
        fetches = [node["Heap Fetches"] for node in nodes if "Heap Fetches" in node]
        return PlanSummary(
            execution_ms=float(document["Execution Time"]),
            pages=int(root["Shared Hit Blocks"]) + int(root["Shared Read Blocks"]),
            node_types=tuple(node["Node Type"] for node in nodes),
            index_names=tuple(dict.fromkeys(node["Index Name"] for node in nodes if "Index Name" in node)),
            rows_removed_by_filter=sum(int(node.get("Rows Removed by Filter", 0)) for node in nodes),
            heap_fetches=int(fetches[0]) if fetches else None,
        )
    except (KeyError, TypeError) as error:
        raise PlanParseError(f"unexpected JSON plan shape: missing {error}") from error
```

`_json_nodes` is a **generator** function: `yield node` hands out the current node, then `yield from _json_nodes(child)` hands out all the nodes of each child, so the whole plan tree is walked one node at a time. This is **recursion**: the function calls itself. `node.get("Plans", [])` returns the value of the key `"Plans"` or an empty list if the key is missing. `parse_json_plan` reads the same facts from the JSON form of a plan. A **list comprehension** `[node["Heap Fetches"] for node in nodes if "Heap Fetches" in node]` picks the values from nodes that have the key. The whole body sits in `try:`; `except (KeyError, TypeError) as error:` catches the two kinds of errors a differently shaped document can cause (a missing key; a value of the wrong type) and re-raises them as a `PlanParseError` with `from error`, which keeps the original as the cause.


### `application/list_orders.py`

`src/busy_listing/application/list_orders.py`, lines 1 to 20:

```python
"""Use case: one page of the listing, by the strategy the caller asks for."""

from __future__ import annotations

from ..domain.listing import ListingRequest, Page, Strategy
from .ports import OrderRepository


class ListOrders:
    """Dispatches a validated request to the repository method of its strategy."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def __call__(self, request: ListingRequest) -> Page:
        if request.strategy is Strategy.NAIVE:
            return self._repository.naive_page(request.page)
        if request.strategy is Strategy.BATCHED:
            return self._repository.batched_page(request.page)
        return self._repository.keyset_page(request.cursor)
```

`ListOrders` is a class that can be *called like a function*: `__call__` is the special method Python runs for `list_orders(request)`. The constructor receives the **repository** (anything with the three `OrderRepository` methods; typing note) and keeps it in `self._repository`. `__call__` looks at `request.strategy` with `is` comparisons and calls the matching method; the last line is the keyset case. All the use case does is choose; the repository does the work.

### `application/health.py`

`src/busy_listing/application/health.py`, lines 1 to 43:

```python
"""Use case: ask every dependency whether it is usable."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .ports import HealthProbe


class ProbeFailedError(Exception):
    """A dependency is not usable; the message says why."""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The outcome of one health probe."""

    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The outcomes of every probe; healthy only when all of them are."""

    results: tuple[ProbeResult, ...]

    @property
    def healthy(self) -> bool:
        return all(result.ok for result in self.results)


def check_health(probes: Iterable[HealthProbe]) -> HealthReport:
    """Run every probe and collect the outcomes; a failed probe is reported, not raised."""
    results = []
    for probe in probes:
        try:
            results.append(ProbeResult(probe.name, True, probe.check()))
        except ProbeFailedError as error:
            results.append(ProbeResult(probe.name, False, str(error)))
    return HealthReport(tuple(results))
```

- `ProbeFailedError(Exception)` is the error a probe raises when its dependency is unhealthy.
- `ProbeResult` and `HealthReport` are dataclasses. `results: tuple[ProbeResult, ...]` is a tuple of results.
- `healthy` uses `all(...)`, which is true only if every element of the generator is true.
- `check_health(probes)` loops over each probe object (anything with `name` and `check()`), calls `probe.check()` inside `try`, and records either a good or a failed result. A failed probe is not re-raised: the report says which one failed.
- `tuple(results)` turns the list into a tuple for the frozen dataclass.


### `application/replay.py`

`src/busy_listing/application/replay.py`, lines 1 to 40:

```python
"""Use case: replay the lesson. The same load four times, ranking the database's statements each time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from ..domain import lesson
from ..domain.errors import LessonInterruptedError
from ..domain.host import HostLoad
from ..domain.plan import PlanSummary, parse_text_plan
from ..domain.statements import RankBy, StatementStat, rank, total_calls, total_time_ms
from .ports import ArtifactStore, IndexLayout, LoadDriver, PlanCapture, StatementStatistics
from .report import render_results


@dataclass(frozen=True, slots=True)
class PhaseResult:
    """What one run of the load cost, and which statements it was made of."""

    label: str
    by_time: tuple[StatementStat, ...]
    by_calls: tuple[StatementStat, ...]
    database_ms: float
    statements: int
    wall_seconds: float
    median_ms_by_page: dict[int, float]


@dataclass(frozen=True, slots=True)
class LessonResult:
    """Everything the replay measured."""

    requests: int
    phases: tuple[PhaseResult, ...]
    plans: dict[str, PlanSummary]
    host_load: HostLoad | None = None


```

`PhaseResult` and `LessonResult` are frozen dataclasses holding what one phase and the whole replay measured (dataclasses note).

`src/busy_listing/application/replay.py`, lines 41 to 91:

```python
class ReplayLesson:
    """Drives the load and the statistics view through the lesson's four phases and keeps the evidence.

    `serve` is a context manager that keeps the listing service running while the load is sent.
    `should_stop` is polled between phases; when it returns true the replay raises `LessonInterruptedError`.
    """

    def __init__(
        self,
        *,
        serve: Callable[[], AbstractContextManager[None]],
        driver: LoadDriver,
        statistics: StatementStatistics,
        indexes: IndexLayout,
        plans: PlanCapture,
        store: ArtifactStore,
        requests: int = 300,
        host_load: HostLoad | None = None,
        progress: Callable[[str], None] = lambda _message: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._serve = serve
        self._driver = driver
        self._statistics = statistics
        self._indexes = indexes
        self._plans = plans
        self._store = store
        self._requests = requests
        self._host_load = host_load
        self._progress = progress
        self._should_stop = should_stop

    def run(self) -> LessonResult:
        """Run the four phases, write the plans and the notes, and return what was measured."""
        captured: dict[str, PlanSummary] = {}
        phases: list[PhaseResult] = []
        with self._serve():
            for index, phase in enumerate(lesson.PHASES):
                self._checkpoint()
                self._progress(phase.label)
                if index in (0, len(lesson.PHASES) - 1):  # the index state changes only before the first and last
                    self._indexes.reset_to(phase.index_step)
                if index == 0:
                    for name in lesson.OFFSET_PLANS:
                        self._capture(name, captured)
                phases.append(self._measure(phase))
                for name in phase.captures:
                    self._capture(name, captured)
        result = LessonResult(self._requests, tuple(phases), captured, self._host_load)
        self._store.save_report(render_results(result))
        return result
```

- `ReplayLesson.__init__` has only keyword-only parameters (everything after the bare `*`). `serve: Callable[[], AbstractContextManager[None]]` is "a function that returns a context manager": calling `serve()` gives something usable in a `with` statement. The replay does not know it is a web server. `requests: int = 300` is the number of requests per phase.
- `run()`: `with self._serve():` keeps the service up for the whole replay and stops it afterwards even on an error. `for index, phase in enumerate(lesson.PHASES):` visits the four phases with a counter (`enumerate` yields `(0, first)`, `(1, second)`...). `if index in (0, len(lesson.PHASES) - 1):` is true for the first and the last phase only: the index state changes before the first (original index) and before the last (covering index). Plans are captured at the right moments, `phases.append(self._measure(phase))` measures. After the `with`, the results are put in a `LessonResult` and the report is saved.

`src/busy_listing/application/replay.py`, lines 93 to 121:

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

    def _capture(self, name: str, captured: dict[str, PlanSummary]) -> None:
        lines = self._plans.capture(name)
        self._store.save_plan(name, lines)
        captured[name] = parse_text_plan(lines)
        self._progress(f"plan {name}: {captured[name].execution_ms:.3f} ms, {captured[name].pages} pages")

    def _checkpoint(self) -> None:
        if self._should_stop():
            raise LessonInterruptedError("stopped between phases")
```

`_measure(phase)` is explained in the pg_stat_statements note. `_capture` saves and parses a plan. `_checkpoint` raises `LessonInterruptedError` if `should_stop()` returns true: a SIGINT or SIGTERM ends the replay between two phases.

### `application/report.py`

`src/busy_listing/application/report.py`, lines 1 to 52:

```python
"""The results notes: a pure function from what was measured to Markdown."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..domain.statements import StatementStat

if TYPE_CHECKING:
    from .replay import LessonResult


def _table(entries: tuple[StatementStat, ...] | list[StatementStat], width: int = 150) -> list[str]:
    rows = ["| Statement | Calls | Total ms | Mean ms |", "|---|---:|---:|---:|"]
    rows += [
        f"| `{entry.short[:width].replace('|', '/')}` | {entry.calls} | {entry.total_ms:.1f} | {entry.mean_ms:.3f} |"
        for entry in entries
    ]
    return rows


def render_results(result: LessonResult) -> str:
    """Markdown with the four-phase table, the plan table and the rankings of the first and last phases."""
    out = [
        "# Results of the last `make run`",
        "",
        f"Generated by `busy-listing-run`: {result.requests} requests per phase, page sequence fixed by seed 1 "
        "(pages 0, 1, 2, 50, 100, 5000 and 10000, chosen at random). The plans are the `.txt` files here.",
        "",
        *([result.host_load.note(), ""] if result.host_load else []),
        "## Same load, four phases",
        "",
        "| Phase | Database time ms | Statements | Wall clock s | Median ms: page 1 | page 100 | page 5,000 "
        "| page 10,000 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for phase in result.phases:
        median = phase.median_ms_by_page
        out.append(
            f"| {phase.label} | {phase.database_ms:.0f} | {phase.statements} | {phase.wall_seconds:.1f} | "
            f"{median.get(0, 0):.1f} | {median.get(100, 0):.1f} | {median.get(5000, 0):.1f} "
            f"| {median.get(10000, 0):.1f} |"
        )
    out += ["", "## Plans for the deep page", "", "| Plan | Execution ms | Pages touched |", "|---|---:|---:|"]
    out += [f"| `{name}` | {plan.execution_ms:.3f} | {plan.pages} |" for name, plan in result.plans.items()]
    for phase in (result.phases[0], result.phases[-1]):
        out += ["", f"## Top ten, phase {phase.label}", "", "### By total time", "", *_table(phase.by_time)]
        out += ["", "### By calls", "", *_table(phase.by_calls)]
    for phase in result.phases[1:-1]:
        out += ["", f"## Top two, phase {phase.label}", ""]
        out += [*_table(phase.by_time[:2]), "", *_table(phase.by_calls[:2])]
    return "\n".join(out) + "\n"
```

- Lines 9 to 11: `if TYPE_CHECKING:` import, to avoid a circular import (typing note).
- `_table(entries, width=150)` returns the lines of a Markdown table. `entry.short[:width].replace('|', '/')` cuts a statement to 150 characters and replaces any pipe, which would break the table, with a slash. The f-string uses `{entry.total_ms:.1f}` and `{entry.mean_ms:.3f}` formats.
- `render_results(result)` builds a list `out` of lines: the heading, the machine-load note when known (`*([result.host_load.note(), ""] if result.host_load else [])` spreads a two-item list or nothing), the four-phase table (one row per phase, `median.get(0, 0)` reads a page's median or 0), the plan table (list comprehension over `result.plans.items()`), the ranking tables for the first and last phases with `*_table(...)`, and shorter tables for the middle phases (`result.phases[1:-1]` slices off the first and last; `phase.by_time[:2]` keeps two rows).

### `interfaces/common.py`

`src/busy_listing/interfaces/common.py`, lines 1 to 45:

```python
"""Startup shared by the programs: settings or a clear exit code 2, and the composition root."""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI

from ..application.health import check_health
from ..application.list_orders import ListOrders
from ..domain.host import HostLoad
from ..infrastructure.health_probes import PostgresListingProbe
from ..infrastructure.logging import configure_logging
from ..infrastructure.orm import create_lab_engine
from ..infrastructure.settings import ConfigurationError, Settings
from ..infrastructure.sqlalchemy_orders import SqlAlchemyOrders
from .http_app import create_app


def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings


def build_app(settings: Settings) -> FastAPI:
    """Wire the use case to its adapters: the one place that knows which implementations are in use."""
    engine = create_lab_engine(settings.postgres, settings.app.pool_size)
    probe = PostgresListingProbe(settings.postgres)
    return create_app(
        ListOrders(SqlAlchemyOrders(engine)),
        settings.app.default_strategy,
        lambda: check_health([probe]),
    )


def measure_host_load() -> HostLoad:
    """The 1-minute load average and CPU count right now, so results can say how busy the machine was."""
    return HostLoad(os.getloadavg()[0], os.cpu_count() or 1)
```

`load_settings()` is the start-up described in the command-line note. `build_app(settings)` is the composition root (FastAPI note). `measure_host_load()` calls `os.getloadavg()[0]` (the 1-minute load average) and `os.cpu_count() or 1`.

### The headers and imports not quoted elsewhere

#### Reading the top of a module

Most modules start with the same three parts, explained once here so that the sections below can be short. First a **docstring**: a text in triple quotes as the very first statement of a file; Python keeps it as the description of the module, and tools show it as help. Then `from __future__ import annotations`, a line that tells Python to treat type hints (the `: int` and `-> str` annotations) as plain text that is not evaluated while the file loads; this lets a hint refer to a class that is defined further down. Then the imports: `import x` makes the module `x` available; `from x import y` brings one name out of it; a dot in front, as in `from .postgres import session`, means "the module `postgres` in this same package" and two dots, `from ..domain.errors import ...`, mean "go up one package, then into `domain`". The logger line `logger = logging.getLogger(__name__)` creates a logger named after the module (`__name__` is the module's dotted name), so every log line says which module wrote it.

##### The `__init__.py` files

A folder is a Python **package** when it contains a file called `__init__.py`. The file may be empty or hold only a docstring, as these do. Each of the four layers has one, and its docstring states the layer's rule.

`src/busy_listing/domain/__init__.py`, lines 1 to 1:

```python
"""The listing and the statistics vocabulary: cursors, pages, strategies, ranked statements. Depends on nothing."""
```

`src/busy_listing/application/__init__.py`, lines 1 to 1:

```python
"""Use cases and the ports they need; no knowledge of PostgreSQL, SQLAlchemy or HTTP."""
```

`src/busy_listing/infrastructure/__init__.py`, lines 1 to 1:

```python
"""Adapters: PostgreSQL through SQLAlchemy, pg_stat_statements, HTTP, files, settings, logging, retries."""
```

`src/busy_listing/interfaces/__init__.py`, lines 1 to 1:

```python
"""Entry points: the HTTP application and the command-line programs."""
```


##### `ports.py`, the rest of the interfaces

A **port** is an interface that the inner layers define and the outer layers implement. Here each is a `typing.Protocol`: a class that lists methods, and any object that has those methods counts as an implementation without having to inherit from it. The bodies are `...` (a literal that means "nothing here"); the docstrings say what each method promises.

`src/busy_listing/application/ports.py`, lines 61 to 67:

```python
    def prepare(self, strategy: Strategy) -> Bookmarks:
        """Look up what the strategy needs before the timed run (keyset bookmarks); outside the statistics."""
        ...

    def run(self, strategy: Strategy, requests: int, bookmarks: Bookmarks) -> LoadTimings:
        """Send `requests` listing requests with the lesson's fixed page sequence."""
        ...
```

`LoadDriver` is the load script. `prepare(strategy)` looks up what the strategy needs before the timed run (the bookmarks for keyset paging) so that this work is not counted in the statistics. `run(strategy, requests, bookmarks)` sends the given number of listing requests in the lesson's fixed page sequence and returns the timings.

`src/busy_listing/application/ports.py`, lines 70 to 79:

```python
class ArtifactStore(Protocol):
    """Where the replay leaves its evidence: the captured plans and the results notes."""

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        """Keep the plan next to its query."""
        ...

    def save_report(self, text: str) -> None:
        """Keep the results notes."""
        ...
```

`ArtifactStore` is where the replay leaves its evidence: `save_plan` keeps a captured plan under its name and `save_report` keeps the results notes.

`src/busy_listing/application/ports.py`, lines 82 to 89:

```python
class HealthProbe(Protocol):
    """A dependency's health check."""

    name: str

    def check(self) -> str:
        """Return a short description of what is healthy. Raise `ProbeFailedError` when it is not."""
        ...
```

`HealthProbe` is a dependency's health check: it has a `name` and a `check()` that returns a short description of what is healthy or raises `ProbeFailedError`.

##### `http_load.py`, the top of the file

`src/busy_listing/infrastructure/http_load.py`, lines 1 to 7:

```python
"""Adapter: the lesson's load script over HTTP. Implements `LoadDriver`.

It clicks through pages the way real users (and bots) do, deep pages included. The same seed gives the same
sequence of pages, so runs before and after a fix are comparable. For keyset paging a page number has no meaning,
so each page is reached from a bookmark: the cursor of the row just before it, looked up once before the timed run
(as a deep link or a saved position would provide).
"""
```

The docstring explains the whole adapter. The load script clicks through pages like real users and bots do, deep pages included. A fixed random seed gives the same page sequence on every run, so runs before and after a fix can be compared. For keyset paging a page number means nothing, so each page is reached from a bookmark, the cursor of the row just before it, looked up once before the timed run, as a deep link or a saved position would provide.

`src/busy_listing/infrastructure/http_load.py`, lines 17 to 19:

```python
from ..domain.cursor import Cursor
from ..domain.lesson import PAGES
from ..domain.listing import PAGE_SIZE, Strategy
```

Three imports from the domain layer: the `Cursor` type, `PAGES` (the list of page numbers the load visits) and, from the listing module, the page size and the `Strategy` enum.

##### `health_probes.py`, the top of the file

`src/busy_listing/infrastructure/health_probes.py`, lines 1 to 1:

```python
"""Adapter: the health check of the one dependency, PostgreSQL."""
```

The docstring: the health check of the one dependency, PostgreSQL.

`src/busy_listing/infrastructure/health_probes.py`, lines 7 to 8:

```python
from ..application.health import ProbeFailedError
from .postgres import scalar, session
```

`ProbeFailedError` is the lab's own error for "this dependency is not usable". `scalar` runs a query and returns its single value; `session` opens a connection for a block of code.

## Try it yourself

1. `.venv/bin/python -c "from busy_listing.domain.listing import Strategy; print(list(Strategy), Strategy.parse('keyset') is Strategy.KEYSET, Strategy.NAIVE == 'naive')"` prints `[<Strategy.NAIVE: 'naive'>, <Strategy.BATCHED: 'batched'>, <Strategy.KEYSET: 'keyset'>] True True`.
2. `.venv/bin/python -c "from busy_listing.domain.listing import *; ListingRequest.of(Strategy.KEYSET, page=3)"` ends with `busy_listing.domain.errors.PageNumberNotSupportedError: keyset paging has no page numbers: pass the cursor from the previous page`.
3. `.venv/bin/python -c "from datetime import UTC, datetime; from busy_listing.domain.cursor import Cursor; t = Cursor(datetime(2026,5,4,11,2,tzinfo=UTC), 832765).encode(); print(t); print(Cursor.decode(t))"` prints a token such as `eyJ0IjoiMjAyNi0wNS0wNFQxMTowMjowMCswMDowMCIsImkiOjgzMjc2NX0` and then `Cursor(created_at=datetime.datetime(2026, 5, 4, 11, 2, tzinfo=datetime.timezone.utc), order_id=832765)`.
4. `.venv/bin/python -c "from busy_listing.domain.statements import *; rows=[StatementStat('a',2,10.0),StatementStat('b',9,1.0)]; print(rank(rows, RankBy.TOTAL_TIME)[0].query, rank(rows, RankBy.CALLS)[0].query)"` prints `a b`: the two rankings disagree.
5. `make test` runs the unit tests of all these modules without a database.

## Mistakes people make

- Mixing tabs and spaces for indentation.
- Using a mutable default (`def f(x=[])`): the same list is shared by every call.
- Comparing with `is` where `==` was meant.
- Forgetting that a `list` assigned to a second name is the same list.
- Catching `Exception` and hiding bugs.
- Using `==` to compare floats exactly.

**How this repository avoids them.** Defaults are never mutable (lambda defaults and tuples). Errors are specific classes with messages written for the caller. Dataclasses are frozen. A request object can only be built valid (`ListingRequest.of`). Division is guarded. Every module has a docstring (ruff `D100`).

## Check yourself

1. What does `if __name__ == "__main__":` guard? *Code that must run only when the file is started as a program, not when imported.*
2. What does the `*` in `def f(a, *, b)` mean? *Everything after it, here `b`, can only be passed by name.*
3. What does `with open(path) as f:` guarantee? *The file is closed when the block ends, also if an error is raised.*
4. What is the difference between a list and a tuple? *A list can be changed after creation; a tuple cannot.*
5. What does `raise Error("x") from cause` add? *It records `cause` as the original reason, so the traceback shows both.*

## Further reading

- The Python Tutorial (3.13): https://docs.python.org/3.13/tutorial/index.html
- Language Reference, "Compound statements" and "Expressions": https://docs.python.org/3.13/reference/index.html
- This repository requires Python 3.12 or newer (`requires-python = ">=3.12"`) and was run on 3.13.12; CI uses 3.12.

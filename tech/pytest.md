# pytest

## What it is

**pytest** is a Python tool for writing and running **tests**: small functions that check that your code does what you think. You write a function whose name starts with `test_`, use the plain Python statement `assert condition` inside it, and run `pytest`. It finds all test functions, runs them, and reports which passed and which failed, with the values involved in the failing `assert`.

## Why this repository uses it

Every "Done when" line of the lesson is a test, and every rule of the quality bar that can be tested is tested. There are 98 unit tests (no database, no network, about two seconds), 18 integration tests (the real database and ORM) and 3 end-to-end tests (the running service and the commands).

## Where it appears

| File | Role |
|---|---|
| `pyproject.toml` | `[tool.pytest.ini_options]`: where tests are, flags, one filtered warning, markers. |
| `tests/unit/` | Fast tests of `domain`, `application`, `infrastructure` (without a database) and `interfaces`. |
| `tests/unit/application/fakes.py` | The fake repository, statistics, driver, indexes, plans, store and server. |
| `tests/integration/conftest.py`, `test_lesson_outcomes.py`, `test_adapters.py` | Tests against the seeded database. |
| `tests/e2e/test_replay_and_service.py` | The service and the commands. |
| `Makefile` | `test`, `test-integration`, `test-e2e`. |

## How it works underneath

**Discovery.** pytest walks the folders given (or `testpaths` from the configuration) and imports every file named `test_*.py` or `*_test.py`. In each it collects functions named `test_*` (and methods of classes named `Test*`).

**Assertions.** `assert a == b`. pytest rewrites the statement when it imports the test file so that, on failure, it prints what `a` and `b` were. Passing means the function returns without an error.

**Expected errors.** `with pytest.raises(SomeError, match="text"):` passes only if the block raises that error and its message matches the regular expression.

**Fixtures.** A **fixture** is a function marked `@pytest.fixture` that prepares something a test needs. A test asks for it by writing the fixture's name as a parameter, and pytest runs the fixture first and passes in the result. A fixture that uses `yield value` hands the value to the test and runs the code after `yield` as clean-up when the test ends. `scope="session"` creates the fixture once per run instead of once per test. Fixtures placed in a file called **`conftest.py`** are available to all tests in that folder and below.

**Built-in fixtures used here.**

- `tmp_path`: a fresh empty temporary folder (a `Path`) for each test.
- `monkeypatch`: changes things for one test and undoes them afterwards: `setenv`/`delenv` (environment variables), `setattr(obj, "name", value)` (replace an attribute).
- `capsys`: captures what the test prints; `capsys.readouterr()` returns `.out` and `.err`.

**Parametrization.** `@pytest.mark.parametrize("name", [v1, v2, ...])` runs the same test once per value.

**Markers.** `@pytest.mark.integration` tags a test; `pytestmark = pytest.mark.integration` at the top of a file tags all tests in it. `pytest -m integration` runs only the tagged tests. `--strict-markers` makes an unknown marker an error (catching typos); markers are declared in the configuration.

**Fakes.** A test double is a simple object that stands in for something heavy (a database). Tests of the use cases pass a **fake** with the same methods, so they run in milliseconds with no database.

**Test levels.** *Unit* tests check one piece with fakes. *Integration* tests use the real database. *End-to-end* tests start the real program and check its output and exit code.

**Reading the output.** `.` passed, `F` failed, `E` error in set-up, `s` skipped. The last line is the summary: `72 passed in 0.32s`. `-ra` adds a summary of every non-passing test. `-q` is quiet.

## Walkthrough of this repository's use

### Configuration

`pyproject.toml`, lines 67 to 75:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
# Starlette's test client warns that it prefers a newer HTTP library; the warning is about the test tooling only.
filterwarnings = ["ignore:Using `httpx` with `starlette.testclient`:Warning"]
markers = [
    "integration: needs PostgreSQL from docker-compose.yml with the seeded tables (make up db)",
    "e2e: replays the lesson through the command-line program and the HTTP service against PostgreSQL",
]
```

`testpaths = ["tests"]`; `addopts = "-ra --strict-markers"` (`-ra` prints a summary line for every test that did not simply pass; `--strict-markers` rejects unknown markers). `filterwarnings = ["ignore:<message>:Warning"]` hides one warning that FastAPI's test client prints about its own test tooling (the comment above explains). The format is `action:message:category`: `ignore` the warnings whose text starts with the given message and that belong to the category `Warning`, the base class of every warning (the library's own warning class is not one of the standard categories, so the broad one is used). `markers` declares `integration` and `e2e` (`pytest --markers` shows them). `make test` runs `tests/unit` only; the other two targets select by marker.

### A plain unit test and an expected error

`tests/unit/domain/test_cursor.py`, lines 1 to 25:

```python
from datetime import UTC, datetime

import pytest

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.errors import InvalidCursorError

MOMENT = datetime(2026, 5, 4, 11, 2, 0, 123456, tzinfo=UTC)


def test_a_cursor_survives_the_round_trip_with_microseconds():
    token = Cursor(MOMENT, 832765).encode()
    assert Cursor.decode(token) == Cursor(MOMENT, 832765)


def test_the_token_does_not_show_its_shape():
    token = Cursor(MOMENT, 832765).encode()
    assert "created_at" not in token
    assert "=" not in token


@pytest.mark.parametrize("token", ["", "not base64 at all!", "e30", "eyJ0IjoiPz8iLCJpIjoxfQ"])
def test_a_token_this_service_did_not_issue_is_refused(token):
    with pytest.raises(InvalidCursorError):
        Cursor.decode(token)
```

`MOMENT` is a fixed time-zone-aware `datetime`. The first test encodes a cursor, decodes it and checks equality (microseconds included). The second checks the token does not contain `created_at` or a `=`. The third is **parametrized**: `@pytest.mark.parametrize("token", ["", "not base64 at all!", "e30", "eyJ0IjoiPz8iLCJpIjoxfQ"])` runs the test four times, once per token, each expecting `pytest.raises(InvalidCursorError)`: an empty token, text that is not base64, valid base64 of `{}` (missing keys), and valid base64 of a bad time.

`tests/unit/domain/test_listing.py`, lines 12 to 14:

```python
def test_an_unknown_strategy_is_refused_with_the_choices():
    with pytest.raises(UnknownStrategyError, match="naive, batched or keyset"):
        Strategy.parse("fast")
```

`pytest.raises(UnknownStrategyError, match="naive, batched or keyset")`: the block must raise that error and the message must contain the text (`match` is a regular expression searched in the message).

### Testing the web layer without a server

`tests/unit/interfaces/test_http_app.py`, lines 51 to 63:

```python
@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"page": 3}, "cursor"),
        ({"strategy": "fast"}, "unknown strategy"),
        ({"cursor": "garbage"}, "cursor"),
        ({"strategy": "naive", "page": -1}, "page"),
    ],
)
def test_a_bad_request_is_a_400_that_says_what_to_change(params, message):
    response = client().get("/orders", params=params)
    assert response.status_code == 400
    assert message in response.json()["error"]
```

`@pytest.mark.parametrize(("params", "message"), [...])` runs the test four times with pairs of values. `client().get("/orders", params=params)` calls the FastAPI app in-process through `TestClient` (FastAPI note); the test checks the status code `400` and that the error message mentions the right word.

### Test doubles

`tests/unit/application/fakes.py`, lines 1 to 60:

```python
"""In-memory stand-ins for the ports, so the use cases can be tested without a database or a server."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.listing import PAGE_SIZE, ListedOrder, Page, Strategy
from busy_listing.domain.load import Bookmarks, LoadTimings
from busy_listing.domain.statements import StatementStat

MOMENT = datetime(2026, 5, 4, 11, 2, tzinfo=UTC)


def order(order_id: int) -> ListedOrder:
    return ListedOrder(order_id, 1, "Customer 1", "paid", "10.00", MOMENT)


class FakeRepository:
    """Records which method was asked for, with what."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def naive_page(self, page: int) -> Page:
        self.calls.append(("naive", page))
        return Page((order(1),))

    def batched_page(self, page: int) -> Page:
        self.calls.append(("batched", page))
        return Page((order(2),))

    def keyset_page(self, after: Cursor | None, page_size: int = PAGE_SIZE) -> Page:
        self.calls.append(("keyset", after))
        return Page((order(3),), Cursor(MOMENT, 3))


class FakeStatistics:
    """Statements that depend on which strategy the fake driver last ran."""

    def __init__(self) -> None:
        self.resets = 0
        self.current: list[StatementStat] = []

    def reset(self) -> None:
        self.resets += 1

    def snapshot(self) -> list[StatementStat]:
        return self.current


class FakeDriver:
    """Pretends to send requests; sets what the statistics will show for the strategy."""

    def __init__(self, statistics: FakeStatistics) -> None:
        self._statistics = statistics
        self.runs: list[tuple[Strategy, int]] = []

```

`FakeRepository` implements the same three methods as the `OrderRepository` port but only records which method was called and with what (`self.calls.append(("naive", page))`), returning a canned `Page`. `FakeStatistics`, `FakeDriver` and the others do the same for the other ports. The later part of `fakes.py` (lines 61 to 128) has `FakeIndexes`, `FakePlans`, `RecordingStore` and `FakeServer`, a context manager that records `"up"` and `"down"`. With them, `tests/unit/application/test_replay.py` checks the order of phases (`Strategy.NAIVE, BATCHED, KEYSET, KEYSET`), that five warm-up requests precede each measured run (`[5, 40] * 4`), that the statistics are reset four times, that the service is up for the whole replay and down afterwards even when the replay is interrupted, and that the index state changes only before the first and last phases.

### monkeypatch, capsys and tmp_path

`tests/unit/interfaces/test_cli.py`, lines 9 to 33:

```python
def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert serve_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err


def test_health_is_exit_1_when_the_probe_fails(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")

    class Failing:
        name = "postgres"

        def __init__(self, _settings) -> None:
            pass

        def check(self) -> str:
            raise ProbeFailedError("pg_stat_statements is not installed; run make db")

    monkeypatch.setattr(health_cli, "PostgresListingProbe", Failing)
    assert health_cli.main([]) == 1
    assert "FAIL postgres: pg_stat_statements" in capsys.readouterr().out

```

`monkeypatch.delenv("PGPASSWORD", raising=False)` removes an environment variable for the test (without failing if it is unset); `monkeypatch.setenv(...)` sets one. `capsys.readouterr().err` is what the command wrote to standard error. In the second test a small class `Failing` stands in for the real probe and `monkeypatch.setattr(health_cli, "PostgresListingProbe", Failing)` replaces the name **inside the `health_cli` module** for this test only; the test then checks the exit code and the printed line.

`tests/unit/interfaces/test_cli.py`, lines 75 to 83:

```python
def test_the_serve_command_runs_the_app_on_the_configured_address(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setenv("APP_PORT", "9123")
    served: dict[str, object] = {}
    monkeypatch.setattr(serve_cli, "build_app", lambda _settings: "the-app")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: served.update(app=app, **kwargs))
    assert serve_cli.main([]) == 0
    assert served["app"] == "the-app"
    assert (served["host"], served["port"]) == ("127.0.0.1", 9123)
```

`monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: served.update(app=app, **kwargs))` replaces `uvicorn.run` with a function that records its arguments, so the test checks that the serve command passes the configured host and port without starting a server.

`tmp_path` appears in `tests/unit/infrastructure/test_artifacts.py` and in the end-to-end tests: a fresh empty folder per test.

### Other unit test files

- `domain/test_statements.py`: merging rows with the same text, the two rankings, the means, totals.
- `domain/test_load.py`, `test_host.py`, `test_plan.py`: small values and the plan parser.
- `application/test_report.py`: calls `render_results` and checks exact table rows, including a pipe in a statement.
- `infrastructure/test_retry.py`, `test_logging_and_shutdown.py`, `test_settings.py`, `test_sql_script.py`: the same kinds of tests as described for these helpers in their notes (a `Flaky` callable; an in-memory stream `io.StringIO`; a real signal raised with `signal.raise_signal`; parametrized bad settings).

### Integration tests

`tests/integration/conftest.py`, lines 19 to 52:

```python
@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings.from_env()


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Engine:
    return create_lab_engine(settings.postgres, settings.app.pool_size)


@pytest.fixture
def orders(engine: Engine) -> SqlAlchemyOrders:
    return SqlAlchemyOrders(engine)


@pytest.fixture
def statistics(settings: Settings) -> PgStatStatements:
    return PgStatStatements(settings.postgres)


@pytest.fixture
def indexes(settings: Settings) -> Iterator[PostgresLabIndexes]:
    """The index state, reset to the original ordering index before and after each test."""
    lab = PostgresLabIndexes(settings.postgres, settings.sql_dir)
    lab.reset_to(0)
    yield lab
    lab.reset_to(0)


@pytest.fixture
def connection(settings: Settings) -> Iterator[psycopg.Connection[Any]]:
    with postgres.session(settings.postgres) as live:
        yield live

```

`@pytest.fixture(scope="session")` builds the settings and the SQLAlchemy engine once per run. `orders` builds the repository per test. `indexes` resets the table to "original index only" before the test (`lab.reset_to(0)`), hands it over with `yield lab`, and resets again afterwards, so tests cannot affect one another. `connection` opens a session.

`tests/integration/test_lesson_outcomes.py`, lines 63 to 69:

```python
def test_step2_a_page_issues_two_statements_or_fewer_once_the_n_plus_one_is_fixed(orders, statement_counter):
    orders.naive_page(5)
    assert statement_counter.count >= 15, "one orders query plus one customer query per order"
    for fetch in (lambda: orders.batched_page(5), lambda: orders.keyset_page(None)):
        before = statement_counter.count
        fetch()
        assert statement_counter.count - before <= 2
```

`test_step2_...` uses the `statement_counter` fixture (SQLAlchemy note): the naive page must send at least 15 statements; the batched page and the keyset page at most 2.

`tests/integration/test_lesson_outcomes.py`, lines 115 to 139:

```python
def test_step4_every_order_exactly_once_while_new_orders_are_inserted(orders, connection, settings):
    highest_id = connection.execute("SELECT max(id) FROM orders").fetchone()[0]
    stop = threading.Event()

    def insert_orders() -> None:
        with session(settings.postgres) as writer:
            while not stop.is_set():
                writer.execute(
                    "INSERT INTO orders (customer_id, status, total, created_at) VALUES "
                    "(1, 'paid', 1, '2027-01-01'), (2, 'paid', 1, '2026-03-01 00:00:00+00'), "
                    "(3, 'paid', 1, '2026-03-01 00:00:00+00')"
                )
                time.sleep(0.002)

    writer_thread = threading.Thread(target=insert_orders)
    writer_thread.start()
    walked, cursor = [], None
    try:
        while True:
            page = orders.keyset_page(cursor, page_size=1000)
            walked += [order.id for order in page.orders]
            cursor = page.next_cursor
            if cursor is None:
                break
    finally:
```

The walk test: a second thread (`threading.Thread`) inserts orders in a loop, using its own connection, until `stop.set()` (a `threading.Event`) while the main thread walks all pages; afterwards the `finally` block stops the thread, counts and deletes the rows it inserted, and the assertions check that every existing order appeared exactly once.

### End-to-end tests

`tests/e2e/test_replay_and_service.py`, lines 15 to 30:

```python
pytestmark = pytest.mark.e2e

# A shared machine can take longer than the 5 s default to accept a connection while the replay runs.
SLOW_MACHINE = {"PG_CONNECT_TIMEOUT_SECONDS": os.environ.get("PG_CONNECT_TIMEOUT_SECONDS", "30")}


def program(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", f"busy_listing.interfaces.{module}", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **SLOW_MACHINE},
        timeout=1800,
        check=False,
    )

```

`SLOW_MACHINE` is a dictionary with one environment variable, `PG_CONNECT_TIMEOUT_SECONDS`, defaulting to `30`: on a busy machine the commands get 30 seconds, not 5, to be accepted by the database. `{**os.environ, **SLOW_MACHINE}` builds the child's environment by copying the current one and adding that entry. `program(...)` starts a command as a separate process with `subprocess.run([...], capture_output=True, text=True, env=..., timeout=1800, check=False)`: capture the output as text, stop it after 30 minutes, and do not raise on a non-zero exit (the test checks `returncode`).

`tests/e2e/test_replay_and_service.py`, lines 32 to 50:

```python
def test_the_service_pages_through_with_an_opaque_cursor_and_refuses_what_it_cannot_answer():
    settings = Settings.from_env()
    base = f"http://{settings.app.host}:{settings.app.port}"
    with running_service(settings):
        health = requests.get(f"{base}/health", timeout=10)
        assert health.status_code == 200
        first = requests.get(f"{base}/orders", timeout=60).json()
        assert first["strategy"] == "keyset"
        assert len(first["orders"]) == 20
        assert all(order["customer_name"].startswith("Customer ") for order in first["orders"])
        second = requests.get(f"{base}/orders", params={"cursor": str(first["next_cursor"])}, timeout=60).json()
        assert not {o["id"] for o in first["orders"]} & {o["id"] for o in second["orders"]}
        assert Cursor.decode(second["next_cursor"]).created_at <= Cursor.decode(first["next_cursor"]).created_at
        assert requests.get(f"{base}/orders", params={"page": 3}, timeout=10).status_code == 400
        assert requests.get(f"{base}/orders", params={"cursor": "garbage"}, timeout=10).status_code == 400
        batched = requests.get(f"{base}/orders", params={"strategy": "batched", "page": "2"}, timeout=60)
        assert batched.status_code == 200
        assert len(batched.json()["orders"]) == 20

```

The first test starts the service in-process (`with running_service(settings):`), calls it with `requests` and checks: health 200, 20 orders, customer names, a second page by cursor with no overlap, 400 for a page number with keyset and for a garbage cursor, and 200 for a batched page.

## Try it yourself

1. `make test` — `98 passed` for the unit tests, then the coverage table, ending with the coverage report for the domain and application folders.
2. `.venv/bin/python -m pytest tests/unit/domain -q` — only the domain tests.
3. `.venv/bin/python -m pytest tests/unit -q -k cursor` — runs only tests whose name contains `cursor`.
4. `.venv/bin/python -m pytest --markers | head` — lists the markers, including the project's two.
5. `.venv/bin/python -m pytest tests/unit/domain/test_cursor.py -q -vv` — verbose names: the parametrized test appears four times with the token in brackets.
6. With the database up: `make test-integration` (18 tests, about a minute) and `make test-e2e` (3 tests, a few minutes).

## Mistakes people make

- A test that depends on another test running first.
- Tests that read the real clock, random numbers or the network and so fail sometimes.
- Asserting too little (a test that cannot fail).
- Catching the error inside the test instead of using `pytest.raises`.
- Leaving shared state (a database table) changed after a test.
- Naming a test file or function without the `test` prefix, so pytest never runs it.

**How this repository avoids them.** Unit tests never touch the network, the clock or the environment except through fixtures and fakes. Integration tests reset the index state before and after, and tests that insert rows delete them in `finally`. Markers are declared and `--strict-markers` is on. Failing-path tests use `pytest.raises` with `match`.

## Check yourself

1. How does pytest know which functions are tests? *They are named `test_*` in files named `test_*.py`.*
2. What is a fixture? *A function that prepares something for tests; a test receives it by naming it as a parameter.*
3. What does `tmp_path` give? *A new empty temporary folder, different for each test.*
4. What does `pytest -m integration` do? *Runs only the tests marked `integration`.*
5. What does `--strict-markers` protect against? *Misspelled or undeclared marker names being silently accepted.*

## Further reading

- pytest documentation (9.1): https://docs.pytest.org/en/stable/ — "Get Started", "How to use fixtures", "How to parametrize", "How to monkeypatch", "How to capture stdout/stderr".

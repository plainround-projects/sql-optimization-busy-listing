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

### The unit tests that every repository shares, line by line

Three of the lab's helper modules are the same in all three repositories: the retry helper, the "how busy was the machine" note, the logging and shutdown helpers, and the health check. Their tests are the same too. This part walks through each file completely. Before the first one, three ideas that every test below uses.

- **A test is a function whose name starts with `test_`.** pytest finds it, calls it with no arguments, and counts it as passed if it returns normally and failed if anything inside it raises an error.
- **`assert` is a Python statement that raises an `AssertionError` when its condition is false.** Everything that "checks" something in these files is an `assert`, or a `with pytest.raises(...)` block that checks that an error does happen.
- **A test double is a stand-in object.** Instead of really sleeping for seconds, or really asking a database a question, a test hands the code under test a small replacement that records what it was asked, so the test is fast and gives the same answer every time.

#### `tests/unit/infrastructure/test_retry.py`

The code under test is `retry`, a function that calls an operation, and if the operation fails with one of a list of error types, waits a moment and tries again. The wait doubles after each failure (1 second, 2 seconds, 4 seconds, 8 seconds, each double the one before) and is then multiplied by a random number between 0.5 and 1.0. That random part is called **jitter**: it stops many clients that failed at the same moment from all retrying at the same moment.

`tests/unit/infrastructure/test_retry.py`, lines 1 to 5:

```python
import random

import pytest

from busy_listing.infrastructure.retry import retry
```

Line 1 imports Python's `random` module, which supplies random numbers and, in the next lines, a random number generator we can seed. Line 3 imports `pytest`, which is needed for `pytest.raises`. Line 5 imports the function under test from the lab's own package. A blank line separates the three groups: the standard library, third-party packages, and this project's own code. That is the order the linter `ruff` enforces.

`tests/unit/infrastructure/test_retry.py`, lines 8 to 16:

```python
class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures, self.calls = failures, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("down")
        return "ok"
```

`Flaky` is a hand-made test double: an operation that fails a chosen number of times and then succeeds.

- `class Flaky:` starts a class, a blueprint for objects.
- `def __init__(self, failures: int) -> None:` is the constructor; Python runs it when you write `Flaky(3)`. `self` is the object being built. `: int` says the argument is a whole number and `-> None` says the function returns nothing; these are type hints that `mypy` checks but Python ignores while running.
- `self.failures, self.calls = failures, 0` stores two values on the object in one line: how many failures to produce, and a counter of calls so far, starting at zero.
- `def __call__(self) -> str:` is a special method name. It makes an object callable, so `Flaky(3)()` runs this method, exactly as if the object were a function. That is what lets `retry` take a `Flaky` where it expects an operation.
- `self.calls += 1` adds one to the counter every time the object is called.
- `if self.calls <= self.failures:` is true for the first `failures` calls, and then `raise ConnectionError("down")` stops the call with an error of that type. `ConnectionError` is a built-in Python error, the kind a database driver raises when the network drops.
- `return "ok"` is reached only on the later calls, which succeed.

`tests/unit/infrastructure/test_retry.py`, lines 19 to 22:

```python
def test_it_returns_the_first_success_without_sleeping():
    pauses: list[float] = []
    assert retry(Flaky(0), attempts=3, base_delay_seconds=1, retry_on=(ConnectionError,), sleep=pauses.append) == "ok"
    assert pauses == []
```

The first test: an operation that never fails (`Flaky(0)`) must come back with its answer and never wait. `pauses: list[float] = []` creates an empty list that will collect every pause the retry helper asks for. The argument `sleep=pauses.append` is the trick: `retry` normally calls `time.sleep` to wait, but here it is told to call `pauses.append` instead, which records the number and returns at once. The call also passes `attempts=3` (give up after three tries), `base_delay_seconds=1` (the first pause would be about one second) and `retry_on=(ConnectionError,)` (the tuple of error types that deserve a retry; the trailing comma makes it a one-item tuple). The line ends with `== "ok"`, so the `assert` checks the returned value. The second `assert` checks that the list of pauses is still empty.

`tests/unit/infrastructure/test_retry.py`, lines 25 to 39:

```python
def test_it_retries_with_doubling_pauses_inside_the_jitter_band():
    pauses: list[float] = []
    operation = Flaky(3)
    result = retry(
        operation,
        attempts=5,
        base_delay_seconds=1,
        retry_on=(ConnectionError,),
        sleep=pauses.append,
        rng=random.Random(1),
    )
    assert result == "ok"
    assert operation.calls == 4
    for pause, ceiling in zip(pauses, (1, 2, 4), strict=True):
        assert ceiling * 0.5 <= pause <= ceiling
```

The second test checks the doubling and the jitter band. `Flaky(3)` fails three times, so the fourth call succeeds. The call is spread over several lines because each argument is on its own line, which is how the formatter lays out a call that is too long for one line. `rng=random.Random(1)` hands `retry` a random number generator started with the **seed** 1. A seeded generator produces the same sequence every run, so the test cannot fail by bad luck. The asserts check that the final answer is `"ok"` and that `operation.calls == 4` (three failures plus the success). The loop `for pause, ceiling in zip(pauses, (1, 2, 4), strict=True):` walks the three recorded pauses together with the three values they may not exceed. `zip` pairs items from two sequences; `strict=True` makes `zip` raise an error if the two sequences have different lengths, which would mean `retry` slept the wrong number of times. Inside the loop, `assert ceiling * 0.5 <= pause <= ceiling` is Python's chained comparison: each pause must be at least half of its ceiling and at most the ceiling, which is the jitter band.

`tests/unit/infrastructure/test_retry.py`, lines 42 to 52:

```python
def test_the_pause_is_capped():
    pauses: list[float] = []
    retry(
        Flaky(4),
        attempts=6,
        base_delay_seconds=10,
        retry_on=(ConnectionError,),
        sleep=pauses.append,
        max_delay_seconds=15,
    )
    assert max(pauses) <= 15
```

The third test checks the cap. With a base delay of 10 seconds the doubled values would be 10, 20, 40 and 80, which is far too long to wait. `max_delay_seconds=15` tells `retry` never to pause longer than 15 seconds before the jitter is applied. `Flaky(4)` fails four times and `attempts=6` leaves room for the fifth call to succeed, so four pauses are recorded. `assert max(pauses) <= 15` takes the largest recorded pause and checks it against the cap. The test does not need a seeded generator, because jitter only shrinks a pause, so the bound holds for every random value.

`tests/unit/infrastructure/test_retry.py`, lines 55 to 59:

```python
def test_the_last_failure_is_raised_after_the_final_attempt():
    operation = Flaky(10)
    with pytest.raises(ConnectionError):
        retry(operation, attempts=3, base_delay_seconds=0, retry_on=(ConnectionError,), sleep=lambda _: None)
    assert operation.calls == 3
```

The fourth test checks what happens when every attempt fails. `Flaky(10)` fails ten times but only three attempts are allowed. `with pytest.raises(ConnectionError):` says "the code inside this block must raise a `ConnectionError`; if it raises nothing, or a different error, the test fails". The pause is `base_delay_seconds=0` and `sleep=lambda _: None` is a one-line function that takes one argument, named `_` because it is ignored, and does nothing; the test does not need to see the pauses, only to avoid waiting. After the block, `assert operation.calls == 3` proves the helper stopped after exactly three tries and raised the last error instead of looping on.

`tests/unit/infrastructure/test_retry.py`, lines 62 to 67:

```python
def test_other_errors_are_not_retried():
    def broken() -> str:
        raise KeyError("x")

    with pytest.raises(KeyError):
        retry(broken, attempts=3, base_delay_seconds=0, retry_on=(ConnectionError,), sleep=lambda _: None)
```

The fifth test checks that only the listed errors are retried. `broken` is a small function defined inside the test that always raises `KeyError("x")`. `retry_on` lists only `ConnectionError`, so a `KeyError` must not be caught: it must come straight out. The blank line after the function is required by the formatter. If `retry` had retried it, the test would still pass the error out after three tries, so the point here is the type: `pytest.raises(KeyError)` shows the original error, not a wrapped one, escapes.

`tests/unit/infrastructure/test_retry.py`, lines 70 to 80:

```python
def test_each_retry_is_reported():
    seen: list[int] = []
    retry(
        Flaky(2),
        attempts=4,
        base_delay_seconds=0,
        retry_on=(ConnectionError,),
        sleep=lambda _: None,
        on_retry=lambda attempt, _: seen.append(attempt),
    )
    assert seen == [1, 2]
```

The sixth test checks the `on_retry` hook, a function `retry` calls before each pause with the attempt number and the error. `seen: list[int] = []` collects the attempt numbers. `on_retry=lambda attempt, _: seen.append(attempt)` is a function that takes two arguments (the second is ignored) and records the first. With `Flaky(2)` the first two calls fail, so the hook is called for attempts 1 and 2 and not for the third, which succeeds. `assert seen == [1, 2]` checks exactly that.

`tests/unit/infrastructure/test_retry.py`, lines 83 to 85:

```python
def test_at_least_one_attempt_is_required():
    with pytest.raises(ValueError, match="attempts"):
        retry(Flaky(0), attempts=0, base_delay_seconds=0, retry_on=(ConnectionError,))
```

The last test checks the guard at the top of `retry`. Asking for zero attempts makes no sense, so the helper raises `ValueError`. `match="attempts"` is a regular expression that pytest searches for in the error's message; it makes sure the message names the bad argument. This call leaves out `sleep` because the helper must fail before it could ever sleep.

#### `tests/unit/domain/test_host.py`

The code under test is `HostLoad`, a small value object that holds the machine's load average (how many programs were waiting for a processor, averaged over the last minute) and the number of processors. It marks the machine as loaded when the load average is more than half the processor count. The lab prints a note about this next to every timing, because milliseconds measured on a busy computer are inflated.

`tests/unit/domain/test_host.py`, lines 1 to 1:

```python
from busy_listing.domain.host import HostLoad
```

The only import: the class under test. The `domain` folder never imports a database driver or the file system, which is why this test needs no setup at all.

`tests/unit/domain/test_host.py`, lines 4 to 7:

```python
def test_a_load_above_half_a_task_per_cpu_is_a_loaded_machine():
    assert HostLoad(40.0, 12).loaded
    assert not HostLoad(3.0, 12).loaded
    assert not HostLoad(6.0, 12).loaded
```

`HostLoad(40.0, 12)` builds a value with load average 40 and 12 CPUs. 40 is more than half of 12, so `.loaded` must be true and the first `assert` passes. `assert not HostLoad(3.0, 12).loaded` uses `not` to say the opposite: 3 is below 6, so the machine is not loaded. The third line tests the boundary: 6.0 on 12 CPUs is exactly half, and the rule is "more than half", so `loaded` is false. Testing the exact boundary is how a mistaken `>=` is caught.

`tests/unit/domain/test_host.py`, lines 10 to 14:

```python
def test_the_note_names_the_load_and_says_what_to_do_when_it_is_high():
    loaded = HostLoad(39.5, 12).note()
    assert "loaded machine (load average 39.5 on 12 CPUs)" in loaded
    assert "rerun `make run`" in loaded
    assert HostLoad(2.0, 12).note() == "Measured at load average 2.0 on 12 CPUs."
```

The second test checks the sentence written into the results file. `HostLoad(39.5, 12).note()` returns the loaded-machine message. `assert "..." in loaded` checks that a piece of text appears inside a longer text, which keeps the test from breaking if the wording around it changes. The two pieces checked are the measured numbers, `loaded machine (load average 39.5 on 12 CPUs)`, and the advice to rerun `make run`; the backticks around `make run` are part of the Markdown the note produces. The last line uses `==` because the quiet-machine sentence is short and fixed: `Measured at load average 2.0 on 12 CPUs.` has to match exactly.

#### `tests/unit/application/test_health.py`

The code under test is `check_health`, which takes a list of **probes** (objects with a `name` and a `check()` method that either returns a short text or raises `ProbeFailedError`) and returns a report that is healthy only if every probe passed. A failing probe must be reported, not allowed to crash the check.

`tests/unit/application/test_health.py`, lines 1 to 1:

```python
from busy_listing.application.health import ProbeFailedError, check_health
```

Imports the error class and the function. `ProbeFailedError` is imported because the test double raises it.

`tests/unit/application/test_health.py`, lines 4 to 11:

```python
class Probe:
    def __init__(self, name: str, error: str | None = None) -> None:
        self.name, self._error = name, error

    def check(self) -> str:
        if self._error:
            raise ProbeFailedError(self._error)
        return "fine"
```

`Probe` is the test double. Its constructor takes a `name` and an optional `error` text (`str | None` means "text or nothing", default `None`). `self.name, self._error = name, error` stores both; the leading underscore on `_error` is a convention for "internal, do not touch from outside". The `check` method raises `ProbeFailedError` with the stored text if one was given, and otherwise returns the word `fine`. `if self._error:` is true for any non-empty text.

`tests/unit/application/test_health.py`, lines 14 to 17:

```python
def test_all_probes_passing_is_healthy():
    report = check_health([Probe("a"), Probe("b")])
    assert report.healthy
    assert [r.detail for r in report.results] == ["fine", "fine"]
```

With two passing probes the report must be healthy. The second `assert` uses a **list comprehension**, `[r.detail for r in report.results]`, which builds a list by taking the `detail` of every result, and compares it with `["fine", "fine"]`.

`tests/unit/application/test_health.py`, lines 20 to 23:

```python
def test_one_failing_probe_is_reported_and_makes_the_report_unhealthy():
    report = check_health([Probe("a"), Probe("b", "down")])
    assert not report.healthy
    assert [(r.name, r.ok, r.detail) for r in report.results] == [("a", True, "fine"), ("b", False, "down")]
```

With one failing probe, the report must not be healthy and must still contain both results in order. The comprehension here builds one tuple per result, `(r.name, r.ok, r.detail)`, and the expected list shows that probe `a` passed with `fine` and probe `b` failed with the message `down`. That the second result exists at all proves the failing probe did not stop the loop.

#### `tests/unit/infrastructure/test_logging_and_shutdown.py`

Two helpers are tested here. `configure_logging` makes every log record come out as one line of **logfmt**, a plain-text format of `key=value` pairs separated by spaces. `ShutdownSignal` is a flag that Ctrl-C (the `SIGINT` signal) or `SIGTERM` sets, so a long loop can notice the request and stop cleanly between two units of work. A **signal** is a small message the operating system sends to a running program; `SIGINT` is what Ctrl-C sends and `SIGTERM` is what `kill` and `docker stop` send by default.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 1 to 6:

```python
import io
import logging
import signal

from busy_listing.infrastructure.logging import configure_logging, fields
from busy_listing.infrastructure.shutdown import ShutdownSignal
```

`io` is the standard library module for streams; `io.StringIO` is a fake file that keeps its text in memory. `logging` is the standard logging module. `signal` gives access to operating-system signals. The last two imports bring in the lab's helpers: `configure_logging` and `fields` (which attaches key and value pairs to a log call), and the `ShutdownSignal` class.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 9 to 19:

```python
def test_a_record_becomes_one_logfmt_line_with_its_fields():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("demo").info("partitions assigned", extra=fields(member="consumer-1", partitions=[0, 1]))
    line = stream.getvalue().strip()
    assert line.startswith("ts=")
    assert "level=INFO" in line
    assert "logger=demo" in line
    assert 'msg="partitions assigned"' in line
    assert "member=consumer-1" in line
    assert 'partitions="[0, 1]"' in line
```

The first test follows one log call from start to finish. `stream = io.StringIO()` is a text buffer standing in for the terminal. `configure_logging("INFO", stream)` tells the logging system to show records of level `INFO` and above and to write them to that buffer in logfmt. `logging.getLogger("demo")` returns the logger named `demo`; `.info("partitions assigned", extra=fields(member="consumer-1", partitions=[0, 1]))` writes one record with extra pairs. `stream.getvalue().strip()` reads everything written so far and removes the trailing newline. The asserts check each piece of the line: it starts with `ts=` (the timestamp), contains `level=INFO` and `logger=demo`, the message in quotes because it contains a space (`msg="partitions assigned"`), the plain pair `member=consumer-1`, and the list shown as text in quotes (`partitions="[0, 1]"`) because its text contains a space.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 22 to 26:

```python
def test_records_below_the_level_are_dropped_():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    logging.getLogger("demo").debug("hidden")
    assert stream.getvalue() == ""
```

A `DEBUG` message is less important than the `INFO` threshold, so it must be dropped: the buffer must still be an empty string.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 29 to 37:

```python
def test_an_exception_is_attached_to_the_line():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("demo").exception("failed")
    assert "exc=" in stream.getvalue()
    assert "boom" in stream.getvalue()
```

When code logs from inside an `except` block with `.exception(...)`, the log line has to carry the error. The test raises a `ValueError` on purpose inside `try:`, catches it with `except ValueError:`, and logs there. It then checks that the line has an `exc=` pair and that the word `boom`, the error's message, appears in it.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 40 to 45:

```python
def test_configuring_twice_does_not_duplicate_lines():
    stream = io.StringIO()
    configure_logging("INFO", stream)
    configure_logging("INFO", stream)
    logging.getLogger("demo").info("once")
    assert stream.getvalue().count("msg=once") == 1
```

Calling `configure_logging` twice must not make every message appear twice. The helper replaces the list of handlers on the root logger (a **handler** is the part of the logging system that sends a record somewhere), and this test proves it: after two calls one `info("once")` produces exactly one `msg=once`, counted with the string method `.count(...)`.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 48 to 52:

```python
def test_a_shutdown_signal_starts_unset_and_is_set_by_request():
    shutdown = ShutdownSignal()
    assert not shutdown.requested
    shutdown.request()
    assert shutdown.requested
```

A new `ShutdownSignal` starts with its flag down (`requested` is false) and `request()` raises it. The class stores the flag in a `threading.Event`, a thread-safe on/off switch, and this test checks the public behavior without caring how it is stored.

`tests/unit/infrastructure/test_logging_and_shutdown.py`, lines 55 to 64:

```python
def test_sigterm_sets_the_flag_once_installed():
    shutdown = ShutdownSignal()
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        shutdown.install()
        signal.raise_signal(signal.SIGTERM)
        assert shutdown.requested
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
```

The last test sends a real signal to the test process. `signal.getsignal(number)` returns whatever function currently handles that signal; the dictionary comprehension saves the handlers for `SIGINT` and `SIGTERM` in `previous`, because the test is about to replace them and must put them back so that it does not disturb the other tests or pytest itself. `shutdown.install()` registers the helper's handler for both signals. `signal.raise_signal(signal.SIGTERM)` makes the process send itself a `SIGTERM`; the handler runs and sets the flag, so `assert shutdown.requested` passes. The `finally:` block runs whether or not the assert passed, and the loop in it calls `signal.signal(number, handler)` to restore every saved handler.

### The remaining unit tests of this repository, line by line

These are the unit test files that belong to this repository alone, plus the shared fakes they rely on. Each is quoted completely and then explained. Two reminders about pytest. **`pytest.raises(SomeError, match="text")`** is a block that passes only if the code inside raises that error and the error's message contains the given text (the `match` value is a regular expression searched in the message). **`@pytest.mark.parametrize("name", [a, b, c])`** placed above a test function runs that function once for each listed value, giving the value to the argument called `name`; each run is reported as its own test.

#### `tests/unit/domain/test_statements.py`

The code under test works on the rows of the PostgreSQL view `pg_stat_statements`, which keeps, for every distinct SQL statement, how many times it ran and how much time it used in total. The lesson ranks statements in two ways (by total time and by number of calls) and the two rankings find different statements.

`tests/unit/domain/test_statements.py`, lines 1 to 12:

```python
from busy_listing.domain.statements import RankBy, StatementStat, merge_by_text, rank, total_calls, total_time_ms

LOOKUP = "SELECT name FROM customers WHERE id = $1"
LISTING = "SELECT * FROM orders ORDER BY created_at DESC OFFSET $1"


def rows() -> list[StatementStat]:
    return [
        StatementStat(LOOKUP, 3000, 15.0),
        StatementStat(LOOKUP, 3000, 18.0),  # the same text under a second query id (int2 against int4)
        StatementStat(LISTING, 300, 5000.0),
    ]
```

Line 1 imports the names under test: the `StatementStat` value object (query text, number of calls and total milliseconds), the `RankBy` choice, and the functions `merge_by_text`, `rank`, `total_calls` and `total_time_ms`. `LOOKUP` is the cheap statement that fetches one customer's name; the `$1` is how PostgreSQL shows a value that was sent separately from the SQL text. `LISTING` is the expensive paging statement with an `OFFSET`. The helper `rows()` builds a fresh list of three statistics each time it is called. The comment on line 10 explains a real-world quirk: `pg_stat_statements` identifies statements by a query id that depends on the types of the parameters, and the database driver sends a small integer as `int2` and a larger one as `int4`, so the same text can appear twice under two ids. The lookup is therefore listed twice, with 3000 calls each.

`tests/unit/domain/test_statements.py`, lines 15 to 18:

```python
def test_rows_with_the_same_text_are_added_together():
    merged = {row.query: row for row in merge_by_text(rows())}
    assert merged[LOOKUP] == StatementStat(LOOKUP, 6000, 33.0)
    assert len(merged) == 2
```

`merge_by_text` must add together the rows that have the same text. The dictionary comprehension `{row.query: row for row in ...}` builds a dictionary from query text to row. The merged lookup row must equal a row made by hand with 6000 calls and 33.0 ms (15.0 plus 18.0), and the dictionary must have two entries, not three.

`tests/unit/domain/test_statements.py`, lines 21 to 23:

```python
def test_the_two_rankings_find_different_statements():
    assert rank(rows(), RankBy.TOTAL_TIME)[0].query == LISTING
    assert rank(rows(), RankBy.CALLS)[0].query == LOOKUP
```

The lesson's key lesson: `rank(rows(), RankBy.TOTAL_TIME)[0]` takes the first (highest) entry of the ranking by time and expects the paging statement, which used 5000 ms in total. The ranking by calls puts the cheap lookup first, with 6000 calls against 300.

`tests/unit/domain/test_statements.py`, lines 26 to 27:

```python
def test_the_ranking_is_cut_to_the_limit():
    assert len(rank(rows(), RankBy.CALLS, limit=1)) == 1
```

`rank` accepts a `limit`. With `limit=1` the list has exactly one entry.

`tests/unit/domain/test_statements.py`, lines 30 to 32:

```python
def test_mean_time_is_total_over_calls_and_zero_for_no_calls():
    assert StatementStat(LISTING, 300, 5000.0).mean_ms == 5000.0 / 300
    assert StatementStat(LISTING, 0, 0.0).mean_ms == 0.0
```

The mean time of a statement is its total time divided by its call count, here 5000.0 over 300. A statement with zero calls has a mean of `0.0` instead of a division by zero.

`tests/unit/domain/test_statements.py`, lines 35 to 36:

```python
def test_a_statement_is_shown_on_one_line():
    assert StatementStat("SELECT 1\n  FROM t\n", 1, 1.0).short == "SELECT 1 FROM t"
```

`short` turns a multi-line statement into one line for a table: `split()` with no argument cuts at any run of white space (spaces, tabs, line breaks) and the pieces are joined again with single spaces.

`tests/unit/domain/test_statements.py`, lines 39 to 41:

```python
def test_totals_cover_every_statement():
    assert total_time_ms(rows()) == 5033.0
    assert total_calls(rows()) == 6300
```

The totals add everything: 33.0 plus 5000.0 gives 5033.0 ms, and 3000 plus 3000 plus 300 gives 6300 calls.

#### `tests/unit/domain/test_listing.py`

The listing can be fetched in three ways, called strategies: `naive` (offset paging with one customer lookup per order), `batched` (offset paging with the customers fetched in one query) and `keyset` (paging that continues after a remembered row). `Strategy` is an enum, a fixed set of named choices; `ListingRequest` is a validated request.

`tests/unit/domain/test_listing.py`, lines 1 to 5:

```python
import pytest

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.errors import InvalidPageError, PageNumberNotSupportedError, UnknownStrategyError
from busy_listing.domain.listing import ListingRequest, Strategy
```

The imports: `pytest`, the `Cursor` class, three error classes, and `ListingRequest` and `Strategy`.

`tests/unit/domain/test_listing.py`, lines 8 to 9:

```python
def test_a_strategy_is_found_by_its_name():
    assert [Strategy.parse(name) for name in ("naive", "batched", "keyset")] == list(Strategy)
```

`Strategy.parse(name)` finds a choice by its text. The comprehension parses the three names in order and the result must equal `list(Strategy)`, the list of all choices in their definition order. If someone adds a fourth strategy, this test fails and reminds them to update it.

`tests/unit/domain/test_listing.py`, lines 12 to 14:

```python
def test_an_unknown_strategy_is_refused_with_the_choices():
    with pytest.raises(UnknownStrategyError, match="naive, batched or keyset"):
        Strategy.parse("fast")
```

An unknown name must raise `UnknownStrategyError`, and the message must list the valid choices (`naive, batched or keyset`) so that whoever typed the wrong word knows what to type instead.

`tests/unit/domain/test_listing.py`, lines 17 to 19:

```python
def test_offset_strategies_take_a_page_number():
    request = ListingRequest.of(Strategy.BATCHED, page=7)
    assert (request.strategy, request.page, request.cursor) == (Strategy.BATCHED, 7, None)
```

`ListingRequest.of(Strategy.BATCHED, page=7)` builds a request. The offset strategies take a page number, so the request carries `page` 7 and no cursor. Comparing a tuple of three attributes with a tuple of three expected values checks them all in one assert.

`tests/unit/domain/test_listing.py`, lines 22 to 25:

```python
def test_keyset_takes_a_cursor_not_a_page_number():
    with pytest.raises(PageNumberNotSupportedError, match="cursor"):
        ListingRequest.of(Strategy.KEYSET, page=3)
    assert ListingRequest.of(Strategy.KEYSET).page == 0
```

Keyset paging has no page numbers; it continues from a cursor. Asking for a page number with it must raise `PageNumberNotSupportedError` whose message mentions `cursor`. Without a page number the request's page is `0`.

`tests/unit/domain/test_listing.py`, lines 28 to 30:

```python
def test_a_negative_page_is_refused():
    with pytest.raises(InvalidPageError):
        ListingRequest.of(Strategy.NAIVE, page=-1)
```

A negative page makes no sense and raises `InvalidPageError`.

`tests/unit/domain/test_listing.py`, lines 33 to 37:

```python
def test_the_cursor_is_carried_through():
    from datetime import UTC, datetime

    cursor = Cursor(datetime(2026, 1, 1, tzinfo=UTC), 5)
    assert ListingRequest.of(Strategy.KEYSET, cursor=cursor).cursor == cursor
```

The cursor passed in must come out unchanged. `Cursor(datetime(2026, 1, 1, tzinfo=UTC), 5)` builds a cursor from a timestamp (with `tzinfo=UTC` so it is an unambiguous point in time) and an order id. The imports sit inside the function because only this test needs them.

#### `tests/unit/domain/test_load.py`

`tests/unit/domain/test_load.py`, lines 1 to 10:

```python
from busy_listing.domain.load import LoadTimings


def test_the_median_of_each_visited_page_is_reported_in_page_order():
    timings = LoadTimings(((100, 30.0), (0, 5.0), (100, 10.0), (100, 20.0), (0, 7.0)), 1.5)
    assert timings.median_by_page() == {0: 6.0, 100: 20.0}


def test_no_requests_means_no_medians():
    assert LoadTimings((), 0.0).median_by_page() == {}
```

`LoadTimings` holds what the load script measured: a tuple of `(page, milliseconds)` pairs for every request and the time the whole run took in seconds. `median_by_page()` returns, for each page visited, the median request time, with the pages in ascending order. In the first test page 0 was timed at 5.0 and 7.0 ms, so its median is the average of the two middle values, 6.0; page 100 was timed at 30, 10 and 20, so the middle value after sorting is 20. The expected result is a dictionary; dictionaries compare equal regardless of order, but the code sorts the pages so that the report lists them in page order. With no requests the result is an empty dictionary.

#### `tests/unit/application/test_list_orders.py`

`ListOrders` is the use case that answers a listing request by asking the repository (the object that talks to the database) the right question for the strategy.

`tests/unit/application/test_list_orders.py`, lines 1 to 13:

```python
from busy_listing.application.list_orders import ListOrders
from busy_listing.domain.listing import ListingRequest, Strategy

from .fakes import MOMENT, FakeRepository


def test_each_strategy_is_answered_by_its_repository_method():
    repository = FakeRepository()
    list_orders = ListOrders(repository)
    list_orders(ListingRequest.of(Strategy.NAIVE, page=3))
    list_orders(ListingRequest.of(Strategy.BATCHED, page=4))
    list_orders(ListingRequest.of(Strategy.KEYSET))
    assert repository.calls == [("naive", 3), ("batched", 4), ("keyset", None)]
```

`MOMENT` and `FakeRepository` come from `fakes.py` (explained below). The fake records each call as a pair of the method name and its argument. The use case object is called like a function (`list_orders(request)`), which works because the class defines `__call__`. After three requests, one per strategy, the recorded calls must be exactly `("naive", 3)`, `("batched", 4)` and `("keyset", None)` in order: each strategy reaches its own repository method, and the keyset request starts from no cursor.

`tests/unit/application/test_list_orders.py`, lines 16 to 19:

```python
def test_keyset_hands_back_the_next_cursor():
    page = ListOrders(FakeRepository())(ListingRequest.of(Strategy.KEYSET))
    assert page.next_cursor is not None
    assert page.next_cursor.created_at == MOMENT
```

For keyset paging the page that comes back must carry the cursor for the next page. The fake returns a page whose next cursor holds `MOMENT`, and the test checks that the cursor exists and has that timestamp. The expression `ListOrders(FakeRepository())(ListingRequest.of(...))` builds the use case and calls it in one line.

#### `tests/unit/application/fakes.py`, the parts used by the replay test

The first half of this file (the repository, the statistics and the order helper) is quoted in the sections about the test doubles above. These are the remaining classes: the stand-ins for the load driver, the index manager, the plan reader, the artifact store and the web server.

`tests/unit/application/fakes.py`, lines 54 to 73:

```python
class FakeDriver:
    """Pretends to send requests; sets what the statistics will show for the strategy."""

    def __init__(self, statistics: FakeStatistics) -> None:
        self._statistics = statistics
        self.runs: list[tuple[Strategy, int]] = []

    def prepare(self, strategy: Strategy) -> Bookmarks:
        return {0: None, 100: "cursor"} if strategy is Strategy.KEYSET else {}

    def run(self, strategy: Strategy, requests: int, bookmarks: Bookmarks) -> LoadTimings:
        self.runs.append((strategy, requests))
        heavy = strategy is not Strategy.KEYSET
        self._statistics.current = [
            StatementStat("SELECT orders OFFSET $1", requests, 5000.0 if heavy else 5.0),
            StatementStat(
                "SELECT customers WHERE id = $1", requests * 20 if strategy is Strategy.NAIVE else requests, 40.0
            ),
        ]
        return LoadTimings(((0, 3.0), (10000, 100.0 if heavy else 3.0)), 2.0)
```

`FakeDriver` replaces the object that sends HTTP requests to the service. `prepare(strategy)` returns the bookmarks the real driver would look up before the timed run; `Bookmarks` is a mapping from page number to cursor, and only the keyset strategy needs it, so the fake returns `{0: None, 100: "cursor"}` for keyset and an empty dictionary otherwise. The expression `a if condition else b` is Python's one-line choice. `run` records what it was asked in `self.runs`, then sets the statistics the fake database will report: `heavy` is true for every strategy except keyset. A heavy strategy reports the paging statement as 5000 ms in total and a light one 5 ms. The customer lookup is called `requests * 20` times for the naive strategy (one per order on a page of 20) and `requests` times otherwise. Finally it returns timings: page 0 took 3 ms and page 10000 took 100 ms for the heavy strategies and 3 ms for keyset, and the run took 2 seconds. The numbers are made up, but they have the shape of the real lesson, which is what lets the replay test check the report logic.

`tests/unit/application/fakes.py`, lines 76 to 83:

```python
class FakeIndexes:
    """Records the index states asked for."""

    def __init__(self) -> None:
        self.states: list[int] = []

    def reset_to(self, step: int) -> None:
        self.states.append(step)
```

`FakeIndexes` records every index state the replay asks for. State 0 is the original ordering index, and state 2 is the covering index after the expand-and-contract migration.

`tests/unit/application/fakes.py`, lines 86 to 99:

```python
class FakePlans:
    """Returns a plan whose time depends on the name."""

    def __init__(self) -> None:
        self.captured: list[str] = []

    def capture(self, name: str) -> tuple[str, ...]:
        self.captured.append(name)
        milliseconds = "100.0" if name.startswith("e1_offset") else "0.05"
        return (
            "Index Scan on orders  (cost=0..1 rows=1)",
            "  Buffers: shared hit=23",
            f"Execution Time: {milliseconds} ms",
        )
```

`FakePlans.capture(name)` pretends to read a query plan. Names that start with `e1_offset` (the deep offset page) get a time of 100.0 ms and the others 0.05 ms. The returned tuple is plan text: an `Index Scan` line, a buffers line of 23 pages, and an `Execution Time` line built with an f-string.

`tests/unit/application/fakes.py`, lines 102 to 113:

```python
class RecordingStore:
    """Keeps what the replay saves."""

    def __init__(self) -> None:
        self.plans: dict[str, tuple[str, ...]] = {}
        self.report: str | None = None

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self.plans[name] = tuple(lines)

    def save_report(self, text: str) -> None:
        self.report = text
```

`RecordingStore` keeps what the replay saves, plans by name and the report text (initially `None`, shown by the type `str | None`).

`tests/unit/application/fakes.py`, lines 116 to 128:

```python
class FakeServer:
    """Counts how often the service was started and stopped."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def __call__(self) -> Iterator[None]:
        self.events.append("up")
        try:
            yield
        finally:
            self.events.append("down")
```

`FakeServer` stands in for the web service. `@contextmanager` is a decorator that turns a function with one `yield` into something usable in a `with` block: the code before `yield` runs on entering the block and the code after it runs on leaving. Here entering records `"up"` and leaving records `"down"`. The `try`/`finally` makes `"down"` be recorded even if the block ends with an error, which is the behavior the replay test relies on.

#### `tests/unit/application/test_replay.py`

`ReplayLesson` runs the lesson's four phases: it starts the service, then for each phase sets the index state, warms the caches with a few requests, resets the statistics, sends the measured requests, reads the statistics, captures the plans, and finally writes the notes.

`tests/unit/application/test_replay.py`, lines 1 to 8:

```python
import pytest

from busy_listing.application.replay import ReplayLesson
from busy_listing.domain import lesson
from busy_listing.domain.errors import LessonInterruptedError
from busy_listing.domain.listing import Strategy

from .fakes import FakeDriver, FakeIndexes, FakePlans, FakeServer, FakeStatistics, RecordingStore
```

Imports, including the lesson data module and the fakes.

`tests/unit/application/test_replay.py`, lines 11 to 23:

```python
def build(**options):
    statistics, indexes, plans, store, server = (
        FakeStatistics(),
        FakeIndexes(),
        FakePlans(),
        RecordingStore(),
        FakeServer(),
    )
    driver = FakeDriver(statistics)
    replay = ReplayLesson(
        serve=server, driver=driver, statistics=statistics, indexes=indexes, plans=plans, store=store, **options
    )
    return replay, driver, statistics, indexes, plans, store, server
```

`build(**options)` creates one of every fake and wires them into a `ReplayLesson`. The tuple assignment `a, b, c = (x, y, z)` creates five fakes at once; the formatter put each on its own line because the line would be too long. `serve=server, driver=driver, ...` are keyword arguments. `**options` passes on any extra options a test wants, such as `requests=40`. The function returns every object so that each test can pick the ones it needs; the `*_` and `*_,` in later tests is Python's way of ignoring the rest of a tuple.

`tests/unit/application/test_replay.py`, lines 26 to 35:

```python
def test_the_four_phases_run_in_the_lessons_order_with_the_same_number_of_requests():
    replay, driver, *_ = build(requests=40)
    replay.run()
    measured = [run for run in driver.runs if run[1] == 40]
    assert [strategy for strategy, _ in measured] == [
        Strategy.NAIVE,
        Strategy.BATCHED,
        Strategy.KEYSET,
        Strategy.KEYSET,
    ]
```

`replay, driver, *_ = build(requests=40)` keeps the first two returned objects and throws the rest away. After the run, `measured` keeps the driver's runs that had 40 requests (the measured ones; the warm-up runs have 5). The strategies of those runs must be naive, batched, keyset and keyset again, the lesson's four phases in order.

`tests/unit/application/test_replay.py`, lines 38 to 42:

```python
def test_the_caches_are_warmed_with_five_requests_before_the_statistics_are_reset():
    replay, driver, statistics, *_ = build(requests=40)
    replay.run()
    assert [run[1] for run in driver.runs] == [5, 40] * 4
    assert statistics.resets == 4
```

Each phase starts with a warm-up of 5 requests, so that the database's memory cache is in the same state for every phase, followed by the measured 40. The list `[5, 40] * 4` repeats that pair four times. The statistics are reset four times, once per phase, after the warm-up so that the warm-up does not count.

`tests/unit/application/test_replay.py`, lines 45 to 48:

```python
def test_the_service_is_up_for_the_whole_replay_and_stopped_afterwards():
    replay, *_, server = build()
    replay.run()
    assert server.events == ["up", "down"]
```

`replay, *_, server = build()` takes the first and the last element. The service must be started once and stopped once: `["up", "down"]`.

`tests/unit/application/test_replay.py`, lines 51 to 55:

```python
def test_the_service_is_stopped_even_when_the_replay_is_interrupted():
    replay, *_, server = build(should_stop=lambda: True)
    with pytest.raises(LessonInterruptedError):
        replay.run()
    assert server.events == ["up", "down"]
```

`should_stop=lambda: True` makes the replay think a stop was requested at its first check. It must raise `LessonInterruptedError`, and the server must still have been stopped, because the shutdown is in a `finally`.

`tests/unit/application/test_replay.py`, lines 58 to 61:

```python
def test_the_index_state_changes_before_the_first_and_the_last_phase_only():
    replay, _driver, _statistics, indexes, *_ = build()
    replay.run()
    assert indexes.states == [0, 2]
```

The index manager is called only twice: state 0 before the first phase and state 2 before the last. Phases 1 to 3 all run with the original index, so there is nothing to change between them.

`tests/unit/application/test_replay.py`, lines 64 to 68:

```python
def test_every_plan_of_the_lesson_is_captured_and_saved():
    replay, _driver, _statistics, _indexes, plans, store, _server = build()
    result = replay.run()
    expected = set(lesson.OFFSET_PLANS) | {name for phase in lesson.PHASES for name in phase.captures}
    assert set(plans.captured) == expected == set(store.plans) == set(result.plans)
```

Every plan named by the lesson, the offset plans plus the captures of each phase, must be captured, saved and listed in the result. The chained comparison `a == expected == b == c` demands that all four sets are equal.

`tests/unit/application/test_replay.py`, lines 71 to 75:

```python
def test_the_top_by_time_and_the_top_by_calls_differ_in_the_naive_phase():
    replay, *_ = build(requests=300)
    first = replay.run().phases[0]
    assert first.by_time[0].query != first.by_calls[0].query
    assert first.by_calls[0].calls == 6000
```

In the naive phase the statement that used the most time is not the statement that was called most often. The fake makes the paging statement heavy and the lookup frequent. `first.by_calls[0].calls == 6000` checks the top of the second ranking: 300 requests times 20 lookups.

`tests/unit/application/test_replay.py`, lines 78 to 81:

```python
def test_the_database_time_falls_across_the_phases():
    replay, *_ = build()
    phases = replay.run().phases
    assert phases[0].database_ms > 100 * phases[-1].database_ms
```

The database time of the first phase must be more than 100 times that of the last. With the fake's numbers, about 5,040 ms against 45 ms, which echoes the shape of the real result.

`tests/unit/application/test_replay.py`, lines 84 to 88:

```python
def test_the_notes_are_saved_once_at_the_end():
    replay, *_, store, _server = build()
    replay.run()
    assert store.report is not None
    assert store.report.startswith("# Results of the last")
```

The notes are saved once, at the end, and begin with the title `# Results of the last`.

`tests/unit/application/test_replay.py`, lines 91 to 96:

```python
def test_progress_is_reported_for_each_phase_and_plan():
    messages: list[str] = []
    replay, *_ = build(progress=messages.append)
    replay.run()
    assert lesson.PHASES[0].label in messages
    assert any(message.startswith("plan e1_offset_page10000") for message in messages)
```

Progress messages are collected through `progress=messages.append`. The first phase's label must appear as a message, and some message must start with `plan e1_offset_page10000`.

#### `tests/unit/application/test_report.py`

`render_results` writes the Markdown of `results.md` from a `LessonResult`.

`tests/unit/application/test_report.py`, lines 1 to 14:

```python
from busy_listing.application.replay import LessonResult, PhaseResult
from busy_listing.application.report import render_results
from busy_listing.domain.plan import PlanSummary
from busy_listing.domain.statements import StatementStat


def phase(label: str, database_ms: float) -> PhaseResult:
    stat = StatementStat("SELECT customers | pipe", 6000, 30.6)
    return PhaseResult(label, (stat,), (stat,), database_ms, 6300, 8.3, {0: 8.7, 100: 10.8, 5000: 49.0, 10000: 85.9})


def result() -> LessonResult:
    plans = {"e1_offset_page10000": PlanSummary(110.0, 200751, (), (), 0, None)}
    return LessonResult(300, tuple(phase(f"phase {n}", 5000.0 / n) for n in (1, 2, 3, 4)), plans)
```

`phase(label, database_ms)` builds one phase result: a statement that used 30.6 ms over 6000 calls (the text contains a pipe character, `|`, on purpose, because a pipe breaks a Markdown table), the same statement as the single entry of both rankings, the database time, 6300 statements, a wall time of 8.3 seconds, and the median time of four pages. `result()` has a `LessonResult` of 300 requests, four phases with database times 5000, 2500, 1666.7 and 1250 (the generator expression divides 5000 by 1, 2, 3 and 4), and one plan, the deep offset page, at 110 ms and 200,751 pages.

`tests/unit/application/test_report.py`, lines 17 to 23:

```python
def test_the_phase_table_shows_database_time_and_page_medians():
    text = render_results(result())
    assert "| phase 1 | 5000 | 6300 | 8.3 | 8.7 | 10.8 | 49.0 | 85.9 |" in text


def test_the_plan_table_lists_the_captured_plans():
    assert "| `e1_offset_page10000` | 110.000 | 200751 |" in render_results(result())
```

The phase table has one row per phase: label, database milliseconds, statements, wall seconds, and the median time of each page. The plan table lists each captured plan with its time and page count.

`tests/unit/application/test_report.py`, lines 26 to 30:

```python
def test_rankings_are_shown_for_the_first_and_last_phase_and_two_rows_for_the_others():
    text = render_results(result())
    assert "## Top ten, phase phase 1" in text
    assert "## Top ten, phase phase 4" in text
    assert "## Top two, phase phase 2" in text
```

The statement rankings are long, so the first and last phase get a top ten (`## Top ten, phase ...`) and the phases in between get only a top two. The labels in the test are `phase 1`, `phase 2`, `phase 3` and `phase 4`, which is why the heading reads `phase phase 1`.

`tests/unit/application/test_report.py`, lines 33 to 34:

```python
def test_a_pipe_in_a_statement_does_not_break_the_table():
    assert "SELECT customers / pipe" in render_results(result())
```

The statement `SELECT customers | pipe` contains a pipe. In the Markdown table it is replaced by a slash, otherwise the table would get an extra column.

`tests/unit/application/test_report.py`, lines 37 to 44:

```python
def test_the_host_load_note_is_printed_when_it_is_known():
    from dataclasses import replace

    from busy_listing.domain.host import HostLoad

    text = render_results(replace(result(), host_load=HostLoad(40.0, 12)))
    assert "Measured on a loaded machine (load average 40.0 on 12 CPUs)" in text
    assert "Measured" not in render_results(result())
```

The host load note is printed when a `HostLoad` is attached. `dataclasses.replace` copies the frozen result with one field changed. Without the load the word `Measured` appears nowhere.

#### `tests/unit/infrastructure/test_settings.py`

`Settings.from_env` reads configuration from a dictionary of environment variables, the named text values a program receives from the shell that starts it. Tests pass a dictionary instead of the real environment, which makes them independent of the machine they run on.

`tests/unit/infrastructure/test_settings.py`, lines 1 to 6:

```python
import pytest

from busy_listing.domain.listing import Strategy
from busy_listing.infrastructure.settings import ConfigurationError, Settings

MINIMAL = {"PGPASSWORD": "s3cret-value"}
```

`MINIMAL` is the one variable that has no default, the database password, set to a harmless made-up value.

`tests/unit/infrastructure/test_settings.py`, lines 9 to 16:

```python
def test_defaults_describe_the_local_compose_setup():
    settings = Settings.from_env(MINIMAL)
    postgres, app = settings.postgres, settings.app
    assert (postgres.host, postgres.port, postgres.database, postgres.user) == ("localhost", 55432, "lab", "lab")
    assert (app.host, app.port, app.default_strategy, app.load_requests) == ("127.0.0.1", 8142, Strategy.KEYSET, 300)
    assert (app.http_timeout_seconds, app.pool_size) == (60, 5)
    assert settings.log_level == "INFO"
    assert settings.sql_dir.name == "sql"
```

With only the password given, everything else takes its default. The database settings: host `localhost`, port `55432` (the lab's database is published on this port so that it does not clash with a PostgreSQL already running on 5432), database and user `lab`. The application settings: the service listens on `127.0.0.1` (this computer only) at port `8142`, uses keyset paging by default, and the load script sends 300 requests. The timeouts: 60 seconds for HTTP requests and a connection pool of 5. The log level is `INFO` and the SQL folder is named `sql`.

`tests/unit/infrastructure/test_settings.py`, lines 19 to 21:

```python
def test_the_database_password_has_no_default():
    with pytest.raises(ConfigurationError, match="PGPASSWORD"):
        Settings.from_env({})
```

No variables at all: a `ConfigurationError` that names `PGPASSWORD`.

`tests/unit/infrastructure/test_settings.py`, lines 24 to 25:

```python
def test_the_password_never_appears_in_a_printed_settings_object():
    assert "s3cret-value" not in repr(Settings.from_env(MINIMAL))
```

The printed form of the settings object (`repr`) must not contain the password.

`tests/unit/infrastructure/test_settings.py`, lines 28 to 49:

```python
def test_every_variable_can_be_overridden():
    settings = Settings.from_env(
        {
            **MINIMAL,
            "PGHOST": "db",
            "PGPORT": "6543",
            "PGDATABASE": "x",
            "PGUSER": "u",
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "9000",
            "LISTING_STRATEGY": "naive",
            "LOAD_REQUESTS": "50",
            "HTTP_TIMEOUT_SECONDS": "5",
            "DB_POOL_SIZE": "2",
            "LAB_SQL_DIR": "/somewhere/sql",
            "LOG_LEVEL": "debug",
        }
    )
    assert (settings.postgres.host, settings.postgres.port) == ("db", 6543)
    assert (settings.app.host, settings.app.port, settings.app.default_strategy) == ("0.0.0.0", 9000, Strategy.NAIVE)
    assert (settings.app.load_requests, settings.app.http_timeout_seconds, settings.app.pool_size) == (50, 5, 2)
    assert (settings.log_level, str(settings.sql_dir)) == ("DEBUG", "/somewhere/sql")
```

Every variable can be overridden. All values in the dictionary are text, because environment variables always are; the settings code converts them. The checks compare tuples of fields: the database host and port (now the number 6543), the application's host `0.0.0.0` (all network interfaces), port 9000 and the `naive` strategy as a `Strategy` value, the load of 50 requests, 5 second timeout, a pool of 2, and finally the log level in upper case (`debug` becomes `DEBUG`) and the SQL folder.

`tests/unit/infrastructure/test_settings.py`, lines 52 to 66:

```python
@pytest.mark.parametrize(
    "extra",
    [
        {"PGPORT": "0"},
        {"APP_PORT": "five"},
        {"PGHOST": "  "},
        {"PG_STATEMENT_TIMEOUT_MS": "-1"},
        {"LISTING_STRATEGY": "fast"},
        {"LOAD_REQUESTS": "0"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_an_unusable_value_is_rejected_with_the_variable_name(extra):
    with pytest.raises(ConfigurationError, match=next(iter(extra))):
        Settings.from_env({**MINIMAL, **extra})
```

This parametrized test runs once for each bad input: a port of `0`, a port that is a word, a host of only spaces, a negative statement timeout, an unknown strategy, zero load requests and a log level that does not exist. Each time the settings must raise `ConfigurationError` and the message must contain the variable's name; `next(iter(extra))` takes the one key of the one-item dictionary and uses it as the pattern.

`tests/unit/infrastructure/test_settings.py`, lines 69 to 71:

```python
def test_settings_read_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "from-the-process")
    assert Settings.from_env().postgres.password == "from-the-process"
```

With no argument `from_env` reads the real process environment. `monkeypatch.setenv` sets a variable for this test only.

#### `tests/unit/interfaces/test_cli.py`

The four command-line programs (`health_cli`, `run_cli`, `serve_cli`, `load_cli`) return an integer exit code: 0 for success, 1 for a failure of the lab and 2 for a configuration problem. The tests call each program's `main` function with a list of arguments rather than starting a new process.

`tests/unit/interfaces/test_cli.py`, lines 1 to 6:

```python
import pytest

from busy_listing.application.health import ProbeFailedError
from busy_listing.domain.listing import Strategy
from busy_listing.domain.load import LoadTimings
from busy_listing.interfaces import health_cli, load_cli, run_cli, serve_cli
```

The imports include all four program modules, the error for a failing probe, the `Strategy` enum and `LoadTimings`.

`tests/unit/interfaces/test_cli.py`, lines 9 to 15:

```python
def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert serve_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err
```

`monkeypatch.delenv("PGPASSWORD", raising=False)` removes the variable for the duration of the test and does not complain if it was not set. Every program must return 2 and the standard error text, read with `capsys.readouterr().err`, must name `PGPASSWORD`.

`tests/unit/interfaces/test_cli.py`, lines 18 to 32:

```python
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

`Failing` is a stand-in for the health probe class: it accepts the settings in its constructor and ignores them, has the `name` `postgres`, and raises a `ProbeFailedError` from `check`. `monkeypatch.setattr(health_cli, "PostgresListingProbe", Failing)` replaces the name inside the `health_cli` module for this test. The program must return 1 and print a line that starts with `FAIL postgres:` followed by the reason.

`tests/unit/interfaces/test_cli.py`, lines 35 to 49:

```python
def test_health_is_exit_0_when_the_probe_passes(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")

    class Passing:
        name = "postgres"

        def __init__(self, _settings) -> None:
            pass

        def check(self) -> str:
            return "1,000,000 orders, pg_stat_statements loaded"

    monkeypatch.setattr(health_cli, "PostgresListingProbe", Passing)
    assert health_cli.main([]) == 0
    assert "ok postgres" in capsys.readouterr().out
```

The mirror case: a probe that returns a description. The program returns 0 and prints a line containing `ok postgres`.

`tests/unit/interfaces/test_cli.py`, lines 52 to 72:

```python
def test_the_load_command_prints_the_median_of_each_page(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    calls: list[tuple[object, ...]] = []

    class Driver:
        def __init__(self, base_url, _postgres, *, timeout_seconds, seed) -> None:
            calls.append((base_url, timeout_seconds, seed))

        def prepare(self, strategy):
            return {}

        def run(self, strategy, requests, bookmarks):
            calls.append((strategy, requests))
            return LoadTimings(((0, 4.0), (100, 9.0)), 1.0)

    monkeypatch.setattr(load_cli, "HttpLoadDriver", Driver)
    assert load_cli.main(["--strategy", "batched", "--requests", "10", "--seed", "3"]) == 0
    assert calls == [("http://127.0.0.1:8142", 60, 3), (Strategy.BATCHED, 10)]
    out = capsys.readouterr().out
    assert "2 requests" in out
    assert "page    100: median      9.0 ms" in out
```

The load program sends requests to the service through a driver class. The test replaces it by `Driver`, whose constructor records the address, the timeout and the random seed in the list `calls`, whose `prepare` returns no bookmarks, and whose `run` records the strategy and request count and returns made-up timings for page 0 and page 100. The program is run with `--strategy batched --requests 10 --seed 3`. The `calls` list must equal the default address `http://127.0.0.1:8142` with the 60 second timeout and the seed 3, then the batched strategy with 10 requests. The printed output must say `2 requests` (the two timings the fake returned) and a line with the median of page 100, `page    100: median      9.0 ms`; the spacing is part of the format.

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

The serve program starts the application with `uvicorn`, a web server. `monkeypatch.setenv("APP_PORT", "9123")` sets the port. `served` is a dictionary that records what the replacement for `uvicorn.run` was called with: `served.update(app=app, **kwargs)` adds the application and the other keyword arguments. `build_app` is also replaced by a function that returns the text `the-app`, so no database is needed. The program must return 0, hand the app to uvicorn, and use host `127.0.0.1` and the configured port 9123.

`tests/unit/interfaces/test_cli.py`, lines 86 to 89:

```python
@pytest.mark.parametrize("argument", ["--requests", "x"])
def test_a_bad_argument_is_rejected_by_the_parser(argument):
    with pytest.raises(SystemExit):
        run_cli.main([argument])
```

This parametrized test runs twice: with `--requests` alone (an option without its value) and with `x` (an argument the parser does not know). `argparse`, Python's command-line parser, prints a usage message and ends the program by raising `SystemExit`.

#### `tests/unit/interfaces/test_http_app.py`

The web application is built with FastAPI. `fastapi.testclient.TestClient` calls it in the same process without opening a network port, so the tests are fast.

`tests/unit/interfaces/test_http_app.py`, lines 1 to 10:

```python
import pytest
from fastapi.testclient import TestClient

from busy_listing.application.health import HealthReport, ProbeResult
from busy_listing.application.list_orders import ListOrders
from busy_listing.domain.cursor import Cursor
from busy_listing.domain.listing import Strategy
from busy_listing.interfaces.http_app import create_app

from ..application.fakes import MOMENT, FakeRepository
```

The imports include `TestClient`, the health report types, the use case, the cursor, `Strategy`, and `create_app`, the function that builds the application from a use case, a default strategy and a function that returns the health report.

`tests/unit/interfaces/test_http_app.py`, lines 13 to 15:

```python
def client(repository: FakeRepository | None = None, healthy: bool = True) -> TestClient:
    report = HealthReport((ProbeResult("postgres", healthy, "fine" if healthy else "down"),))
    return TestClient(create_app(ListOrders(repository or FakeRepository()), Strategy.KEYSET, lambda: report))
```

The helper `client` builds a `HealthReport` with one probe result (healthy or not, with the detail `fine` or `down`) and a `TestClient` around an application that uses the fake repository and the keyset default. The `lambda: report` is the function that returns that report.

`tests/unit/interfaces/test_http_app.py`, lines 18 to 22:

```python
def test_the_default_strategy_answers_when_none_is_asked_for():
    repository = FakeRepository()
    body = client(repository).get("/orders").json()
    assert body["strategy"] == "keyset"
    assert repository.calls == [("keyset", None)]
```

A request to `/orders` with no parameters is answered with the default strategy. `.get("/orders")` sends an HTTP GET request; `.json()` parses the response body (JSON, a text format of keys and values) into a dictionary. The body says `"strategy": "keyset"` and the fake repository recorded exactly one keyset call with no cursor.

`tests/unit/interfaces/test_http_app.py`, lines 25 to 35:

```python
def test_an_order_is_rendered_with_its_customer_and_the_next_cursor():
    body = client().get("/orders").json()
    assert body["orders"][0] == {
        "id": 3,
        "customer_id": 1,
        "customer_name": "Customer 1",
        "status": "paid",
        "total": "10.00",
        "created_at": MOMENT.isoformat(),
    }
    assert Cursor.decode(body["next_cursor"]) == Cursor(MOMENT, 3)
```

An order is rendered with its customer: the id, customer id and name, status, total as text (money is kept as text so that no rounding happens on the way), and the creation time in ISO 8601 form. The `next_cursor` is the opaque token; decoding it with `Cursor.decode` must give the cursor the fake returned.

`tests/unit/interfaces/test_http_app.py`, lines 38 to 41:

```python
def test_offset_strategies_take_a_page_number():
    repository = FakeRepository()
    assert client(repository).get("/orders", params={"strategy": "batched", "page": 7}).status_code == 200
    assert repository.calls == [("batched", 7)]
```

`params={"strategy": "batched", "page": 7}` adds `?strategy=batched&page=7` to the request. The answer is the status code 200 (success) and the repository was asked for batched page 7.

`tests/unit/interfaces/test_http_app.py`, lines 44 to 48:

```python
def test_a_cursor_is_decoded_before_it_reaches_the_repository():
    repository = FakeRepository()
    token = Cursor(MOMENT, 99).encode()
    client(repository).get("/orders", params={"cursor": token})
    assert repository.calls == [("keyset", Cursor(MOMENT, 99))]
```

The cursor token sent by a client is decoded before it reaches the repository: the repository must receive a `Cursor` object equal to the one that was encoded.

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

A parametrized test with two arguments, `params` and `message`: four bad requests. A page number with keyset paging, an unknown strategy, a cursor that is garbage, and a negative page. Each must be answered with status 400 (the client's request is wrong) and the JSON body's `error` text must contain a word that tells the client what to change.

`tests/unit/interfaces/test_http_app.py`, lines 66 to 70:

```python
def test_health_is_200_when_every_check_passes_and_503_when_one_fails():
    healthy = client().get("/health")
    assert healthy.status_code == 200
    assert healthy.json()["checks"]["postgres"] == {"ok": True, "detail": "fine"}
    assert client(healthy=False).get("/health").status_code == 503
```

The `/health` route answers 200 when every check passes, with a body that lists each check (`{"ok": True, "detail": "fine"}` for `postgres`), and 503 (service unavailable) when one fails.

#### `tests/integration/conftest.py`, the remaining lines

These fixtures are explained in the integration section above; the lines below are the imports and the helper that records SQL statements.

`tests/integration/conftest.py`, lines 1 to 1:

```python
"""Fixtures for the tests that need the seeded database from `make up db`."""
```

The module docstring.

`tests/integration/conftest.py`, lines 8 to 14:

```python
from sqlalchemy import Engine, event

from busy_listing.domain.plan import PlanSummary, parse_json_plan
from busy_listing.infrastructure import postgres
from busy_listing.infrastructure.lab_indexes import PostgresLabIndexes
from busy_listing.infrastructure.orm import create_lab_engine
from busy_listing.infrastructure.pg_stat_statements import PgStatStatements
```

`Engine` and `event` come from SQLAlchemy: an `Engine` is the object that manages connections to the database, and `event` lets code listen for what the engine does. The other imports bring in the plan parser, the connection helper, the index manager, the function that builds the engine, the statistics reader and the repository adapter.

`tests/integration/conftest.py`, lines 77 to 80:

```python
def explain(connection: psycopg.Connection[Any], query: str) -> tuple[PlanSummary, dict[str, Any]]:
    """The summary and the raw JSON of a query's plan with real timings and buffers."""
    document: dict[str, Any] = connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query).fetchone()[0][0]  # type: ignore[index]
    return parse_json_plan(document), document
```

The `explain` helper runs a query under `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` and returns both the parsed summary and the raw JSON document. `fetchone()[0][0]` unwraps the row (a one-item tuple) and the list inside it (PostgreSQL returns a list with one plan). The `# type: ignore[index]` comment tells `mypy` to skip its check on this line, since the driver's types say the result might be `None`.

#### `tests/integration/test_adapters.py`

`tests/integration/test_adapters.py`, lines 1 to 1:

```python
"""The adapters that are not the lesson itself: statistics, health, settings against the real database."""
```

The module docstring.

`tests/integration/test_adapters.py`, lines 3 to 8:

```python
import pytest

from busy_listing.application.health import ProbeFailedError
from busy_listing.infrastructure.health_probes import PostgresListingProbe

pytestmark = pytest.mark.integration
```

The imports and the `integration` marker, which makes `make test` (which runs only `tests/unit`) skip this file and `make test-integration` include it.

`tests/integration/test_adapters.py`, lines 11 to 17:

```python
def test_the_statistics_are_empty_after_a_reset_and_count_the_next_statements(orders, statistics):
    statistics.reset()
    assert statistics.snapshot() == []
    orders.keyset_page(None)
    # The driver may add a lowercase `select` of its own (a session setting); the page itself is an uppercase SELECT.
    assert {row.query.split()[0].upper() for row in statistics.snapshot()} == {"SELECT"}
    assert any("orders.created_at" in row.query for row in statistics.snapshot())
```

`statistics.reset()` clears `pg_stat_statements`, and `snapshot()` must return an empty list. One keyset page is then fetched through the ORM. The set comprehension takes the first word of each recorded statement and upper-cases it (the driver may add a lowercase `select` of its own to set up the session, as the comment says) and the result must be only `SELECT`. At least one recorded statement must mention `orders.created_at`, which shows it is the listing query.

`tests/integration/test_adapters.py`, lines 20 to 21:

```python
def test_the_health_probe_reports_the_seeded_orders(settings):
    assert "1,000,000 orders" in PostgresListingProbe(settings.postgres).check()
```

The health probe against the seeded database must say `1,000,000 orders`.

`tests/integration/test_adapters.py`, lines 24 to 29:

```python
def test_the_health_probe_fails_with_a_named_error_when_the_database_cannot_be_reached(settings):
    import dataclasses

    unreachable = dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)
    with pytest.raises(ProbeFailedError, match="cannot query PostgreSQL"):
        PostgresListingProbe(unreachable).check()
```

`dataclasses.replace` copies the settings with port 1 (where nothing listens) and a one second timeout. The probe must turn the driver's connection error into the lab's own `ProbeFailedError` with the message `cannot query PostgreSQL`.

#### `tests/integration/test_lesson_outcomes.py`

One test per "Done when" line of the lesson, against the seeded database. The marker `integration` is set for the whole file by `pytestmark`.

`tests/integration/test_lesson_outcomes.py`, lines 1 to 3:

```python
"""One test per "Done when" line of the lesson, against the seeded database (make up db first)."""

import pathlib
```

The module docstring and the first import, `pathlib`.

`tests/integration/test_lesson_outcomes.py`, lines 11 to 26:

```python
from busy_listing.domain.lesson import PAGES
from busy_listing.domain.statements import RankBy, rank, total_time_ms
from busy_listing.infrastructure.http_load import HttpLoadDriver
from busy_listing.infrastructure.postgres import session

from .conftest import explain

pytestmark = pytest.mark.integration

OFFSET_PAGE = "SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET {offset}"
KEYSET_PAGE = (
    "SELECT id, customer_id, status, total, created_at FROM orders WHERE (created_at, id) < ('{moment}', {order_id}) "
    "ORDER BY created_at DESC, id DESC LIMIT 20"
)
FIRST_PAGE = "SELECT id, customer_id, status, total, created_at FROM orders ORDER BY created_at DESC, id DESC LIMIT 20"
SQL = pathlib.Path(__file__).resolve().parents[2] / "sql"
```

`PAGES` lists the page numbers the load visits. `OFFSET_PAGE` is a paging query with a `{offset}` placeholder, `KEYSET_PAGE` continues after a given `(created_at, id)` pair using a row comparison, and `FIRST_PAGE` is the same query with no condition. The row comparison `(created_at, id) < (moment, order_id)` compares the two values together, first by time and then by id, which matches the sort order `ORDER BY created_at DESC, id DESC`. `SQL` is the path of the repository's `sql` folder.

`tests/integration/test_lesson_outcomes.py`, lines 29 to 47:

```python
def bookmark(connection, page):
    created_at, order_id = connection.execute(
        "SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1", (page * 20 - 1,)
    ).fetchone()
    return created_at, order_id


def keyset_query(connection, page):
    created_at, order_id = bookmark(connection, page)
    return KEYSET_PAGE.format(moment=created_at.isoformat(), order_id=order_id)


def run_load(repository, strategy, pages=40):
    for index in range(pages):
        page = PAGES[index % len(PAGES)]
        if strategy == "naive":
            repository.naive_page(page)
        else:
            repository.batched_page(page)
```

Three helpers. `bookmark(connection, page)` finds the `(created_at, id)` of the last row of the page before the one asked for: it skips `page * 20 - 1` rows with `OFFSET` and reads one. `keyset_query` fills those two values into `KEYSET_PAGE`. `run_load(repository, strategy, pages=40)` simulates users: it visits 40 pages taken from the list of pages in turn (`index % len(PAGES)` wraps around), using the naive method for the naive strategy and the batched one otherwise.

`tests/integration/test_lesson_outcomes.py`, lines 50 to 60:

```python
def test_step1_the_top_by_total_time_and_the_top_by_calls_are_different_queries(orders, statistics, indexes):
    statistics.reset()
    run_load(orders, "naive")
    rows = statistics.snapshot()
    by_time, by_calls = rank(rows, RankBy.TOTAL_TIME)[0], rank(rows, RankBy.CALLS)[0]
    assert "FROM orders" in by_time.query
    assert "OFFSET" in by_time.query
    assert "FROM customers WHERE customers.id = $1" in by_calls.short
    assert by_time.query != by_calls.query
    assert by_calls.calls >= 15 * by_time.calls, "a cheap statement run once per order, per page"
    assert by_time.mean_ms > 100 * by_calls.mean_ms
```

Step 1 of the lesson. After the statistics are cleared and the naive load has run, `statistics.snapshot()` gives the rows. The statement with the most total time must be the paging query (it contains `FROM orders` and `OFFSET`) and the statement with the most calls must be the per-order customer lookup. They must be different statements. The lookup's calls must be at least 15 times the paging query's (one lookup per order on a page), and the paging statement's mean time must be more than 100 times that of the lookup.

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

Step 2. `statement_counter` counts every statement the ORM sends. A naive page needs at least 15 (one query for the orders plus one per customer). For the batched page and the keyset page, a loop over two small functions (lambdas) checks that each sends at most two statements: the orders and one query for all their customers.

`tests/integration/test_lesson_outcomes.py`, lines 72 to 78:

```python
def test_step2_the_per_order_lookup_disappears_from_the_next_ranking(orders, statistics, indexes):
    statistics.reset()
    run_load(orders, "batched", pages=20)
    ranked = rank(statistics.snapshot(), RankBy.CALLS)
    assert not any("customers.id = $1" in row.short for row in ranked)
    lookup = next(row for row in ranked if "= ANY" in row.short)
    assert lookup.calls == 20, "one customer query per page load"
```

After the fix, the per-order lookup must be gone from the ranking by calls. The new customer query uses `= ANY(...)` (match any of a list of ids) and the test requires exactly 20 calls for 20 page loads, one per page.

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

Step 3. `EXPLAIN ANALYZE` of the offset query at offsets 0, 1980 and 199,980. The deep plan's top node is a `Limit` that returned 20 rows, and its child node produced 199,980 plus 20 rows: the database built 200,000 rows to throw almost all of them away. The pages touched must grow with the offset and the deepest page must be more than 20 times slower than the first.

`tests/integration/test_lesson_outcomes.py`, lines 91 to 97:

```python
def test_step4_a_deep_keyset_page_costs_about_what_page_one_costs(connection, indexes):
    first, _ = explain(connection, FIRST_PAGE)
    deep, _ = explain(connection, keyset_query(connection, 10000))
    deep_offset, _ = explain(connection, OFFSET_PAGE.format(offset=199980))
    assert abs(deep.pages - first.pages) <= 10
    assert deep_offset.pages > 1000 * deep.pages
    assert deep.execution_ms * 20 < deep_offset.execution_ms
```

Step 4. The first page, the page 10,000 reached by keyset, and the same page reached by offset are compared. The keyset deep page must touch about as many pages as the first one (within 10), the offset deep page more than 1000 times as many, and the keyset deep page must be at least 20 times faster.

`tests/integration/test_lesson_outcomes.py`, lines 100 to 112:

```python
def test_step4_ties_never_split_a_page_boundary_and_the_cursor_hides_its_shape(orders, connection):
    expected = [
        row[0] for row in connection.execute("SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 11")
    ]
    walked, cursor = [], None
    for _ in range(6):  # pages of 2 cross the groups of three equal timestamps
        page = orders.keyset_page(cursor, page_size=2)
        walked += [order.id for order in page.orders]
        cursor = page.next_cursor
    assert walked[:11] == expected
    assert cursor is not None
    assert "created_at" not in cursor.encode()
    assert Cursor.decode(cursor.encode()) == cursor
```

Rows with equal timestamps must not be split across page boundaries wrongly. `expected` is the first 11 ids in the true order. The loop walks six pages of two rows with the cursor from each page; the data has groups of three rows with the same timestamp, so pages of two cross those groups. The first 11 ids walked must equal the expected ones. The final cursor must exist, must not reveal its shape (`created_at` does not appear in the encoded text, since it is Base64), and must decode back to itself.

`tests/integration/test_lesson_outcomes.py`, lines 115 to 146:

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
        stop.set()
        writer_thread.join()
        inserted = connection.execute("SELECT count(*) FROM orders WHERE id > %s", (highest_id,)).fetchone()[0]
        connection.execute("DELETE FROM orders WHERE id > %s", (highest_id,))
    assert inserted > 0, "the writer really ran during the walk"
    assert len(walked) == len(set(walked)), "no order appeared twice"
    assert set(range(1, highest_id + 1)) <= set(walked), "no existing order was skipped"
```

Keyset paging must show every order exactly once even while new orders arrive. A second thread inserts rows in a loop. `threading.Event` is a thread-safe on/off flag: the writer runs `while not stop.is_set()`, and the main thread sets it when done. The inner function `insert_orders` opens its own connection, because a connection must not be shared by two threads, and inserts three orders per round: one dated in 2027 (newer than everything, so it lands before the first page) and two with an older timestamp equal to existing rows (so they land inside the walk). `time.sleep(0.002)` pauses two milliseconds between rounds. The main thread starts the writer, then walks pages of 1000 rows until the cursor is `None`. The `finally` block always stops the thread, waits for it with `join()`, counts the rows the writer inserted and deletes them again so the database is as it was. The assertions: the writer really inserted something, there are no duplicate ids in what was walked (`len(walked) == len(set(walked))`), and every id that existed before the walk was seen (`set(range(1, highest_id + 1)) <= set(walked)`, a subset test).

`tests/integration/test_lesson_outcomes.py`, lines 149 to 158:

```python
def test_common_mistake_offset_paging_repeats_a_row_when_a_new_order_arrives_between_pages(orders, connection):
    first = [order.id for order in orders.batched_page(0).orders]
    connection.execute(
        "INSERT INTO orders (customer_id, status, total, created_at) VALUES (1, 'paid', 1, '2027-01-01')"
    )
    try:
        second = [order.id for order in orders.batched_page(1).orders]
    finally:
        connection.execute("DELETE FROM orders WHERE created_at = '2027-01-01'")
    assert first[-1] in second, "the last row of page 1 is shown again as the first row of page 2"
```

The first of two tests of common mistakes. Offset paging repeats a row when a new order arrives between two page loads: the test reads page 0, inserts an order dated in 2027 (which becomes the new first row and pushes everything down), reads page 1, and cleans up in `finally`. The last row of page 0 now appears again at the top of page 1.

`tests/integration/test_lesson_outcomes.py`, lines 161 to 174:

```python
def test_common_mistake_a_cursor_on_created_at_alone_skips_tied_orders(connection):
    expected = [
        row[0] for row in connection.execute("SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 12")
    ]
    walked, last_created_at = [], None
    for _ in range(6):
        where = "WHERE created_at < %s" if last_created_at else ""
        rows = connection.execute(
            f"SELECT id, created_at FROM orders {where} ORDER BY created_at DESC, id DESC LIMIT 2",
            (last_created_at,) if last_created_at else (),
        ).fetchall()
        walked += [row[0] for row in rows]
        last_created_at = rows[-1][1]
    assert walked != expected[: len(walked)], "tied rows at the page boundaries were skipped"
```

The second mistake: a cursor made of `created_at` alone. The loop walks six pages of two rows using only the last timestamp (`WHERE created_at < %s`, with an empty condition on the first page). Because several rows share the same timestamp, rows tied at the boundary are skipped, so the ids walked differ from the true order. The assertion demonstrates the bug on purpose: `walked != expected[: len(walked)]`.

`tests/integration/test_lesson_outcomes.py`, lines 177 to 185:

```python
def test_step5_the_covering_index_gives_an_index_only_scan_with_no_heap_visits(connection, indexes):
    query = keyset_query(connection, 10000)
    heap_path, _ = explain(connection, query)
    indexes.reset_to(2)
    covering, _ = explain(connection, query)
    assert covering.has_node("Index Only Scan")
    assert covering.uses_index("idx_orders_listing")
    assert covering.heap_fetches == 0
    assert covering.pages < heap_path.pages
```

Step 5. The deep keyset query is planned first with the original index and then after `indexes.reset_to(2)`, which creates the covering index. The new plan must contain an `Index Only Scan` on `idx_orders_listing` with zero heap fetches and fewer pages than before.

`tests/integration/test_lesson_outcomes.py`, lines 188 to 196:

```python
def test_step5_the_index_change_is_expand_then_contract(connection, indexes):
    def names():
        return {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'orders'")}

    assert names() == {"orders_pkey", "idx_orders_created_id"}
    indexes.reset_to(1)
    assert names() == {"orders_pkey", "idx_orders_created_id", "idx_orders_listing"}, "both exist: no gap"
    indexes.reset_to(2)
    assert names() == {"orders_pkey", "idx_orders_listing"}
```

The change of index is done in two moves, called expand and contract. `names()` returns the set of index names on the table. At the start only the primary key and the old index exist. After state 1 both the old and the new index exist (the comment says "no gap": the listing always has an index to use). After state 2 the old index is gone.

`tests/integration/test_lesson_outcomes.py`, lines 199 to 209:

```python
def test_migrations_run_twice_and_revert_in_reverse_order_without_harm(connection, indexes):
    from busy_listing.infrastructure.sql_script import run_file

    for path in indexes.migrations():
        run_file(connection, path)
        run_file(connection, path)
    for path in reversed(indexes.down_migrations()):
        run_file(connection, path)
        run_file(connection, path)
    names = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'orders'")}
    assert names == {"orders_pkey", "idx_orders_created_id"}, "the downs restore the state before the migrations"
```

Migrations must be safe to run twice and to undo twice. Each up script is run twice in order; each down script is run twice in reverse order (`reversed(...)`). The set of indexes must be exactly what it was at the start.

`tests/integration/test_lesson_outcomes.py`, lines 212 to 224:

```python
def test_step6_the_same_load_costs_far_less_database_time_after_the_fixes(orders, statistics, indexes):
    totals = {}
    for strategy, step in (("naive", 0), ("keyset", 2)):
        indexes.reset_to(step)
        statistics.reset()
        for index in range(60):
            page = PAGES[index % len(PAGES)]
            if strategy == "naive":
                orders.naive_page(page)
            else:
                orders.keyset_page(None)
        totals[strategy] = total_time_ms(statistics.snapshot())
    assert totals["naive"] > 20 * totals["keyset"], "the lesson saw about 42 times less database time"
```

Step 6 compares the whole: the naive strategy with the original index against keyset with the covering index. For each, the index state is set, the statistics are reset, 60 pages are loaded, and the total database time is stored in a dictionary. The naive total must be more than 20 times the keyset total.

`tests/integration/test_lesson_outcomes.py`, lines 227 to 230:

```python
def test_the_seed_script_leaves_tables_that_have_rows_alone():
    seed = (SQL / "002_seed.sql").read_text()
    assert "\\if :orders_empty" in seed
    assert "\\if :customers_empty" in seed
```

The seed script must not reload tables that already contain rows. It does this with the `psql` conditional `\if`; the test checks that the guards for `orders` and `customers` are in the script text.

`tests/integration/test_lesson_outcomes.py`, lines 233 to 242:

```python
def test_the_bookmark_lookup_returns_a_cursor_per_deep_page(settings):
    driver = HttpLoadDriver("http://unused", settings.postgres)
    from busy_listing.domain.listing import Strategy

    bookmarks = driver.prepare(Strategy.KEYSET)
    assert set(bookmarks) == set(PAGES)
    assert bookmarks[0] is None
    created_at, _order_id = (Cursor.decode(str(bookmarks[10000])).created_at, 0)
    assert created_at < datetime(2027, 1, 1, tzinfo=UTC)
    assert driver.prepare(Strategy.NAIVE) == {}
```

`HttpLoadDriver("http://unused", ...)` is built with an address it never uses, because `prepare` only reads the database. For the keyset strategy it must return a bookmark for every page the load visits; page 0 has no cursor; the cursor for page 10,000 decodes to a timestamp before 2027 (the test data has a few rows dated 2027 that must not be used). For the naive strategy `prepare` returns an empty dictionary.

#### `tests/e2e/test_replay_and_service.py`

These tests start real programs and a real web service. They are marked `e2e` and run with `make test-e2e`.

`tests/e2e/test_replay_and_service.py`, lines 1 to 1:

```python
"""The lesson's scenario end to end: the HTTP service answering, and the whole replay (make up db first)."""
```

The module docstring.

`tests/e2e/test_replay_and_service.py`, lines 5 to 5:

```python
import subprocess
```

`re` is Python's regular expression module, used in the health test below.

`tests/e2e/test_replay_and_service.py`, lines 13 to 13:

```python
from busy_listing.interfaces.service import running_service
```

`running_service` is a context manager that starts the web service in the background and stops it on leaving the `with` block.

`tests/e2e/test_replay_and_service.py`, lines 52 to 54:

```python
def test_the_health_command_is_green_on_the_seeded_database():
    result = program("health_cli")
    assert result.returncode == 0, result.stdout + result.stderr
```

The health command, run as a separate process, must exit with 0.

`tests/e2e/test_replay_and_service.py`, lines 58 to 66:

```python
def test_the_replay_ranks_the_statements_four_times_and_writes_the_notes(tmp_path):
    result = program("run_cli", "--output-dir", str(tmp_path), "--requests", "60")
    assert result.returncode == 0, result.stderr
    notes = (tmp_path / "results.md").read_text()
    assert "## Top ten, phase 1 naive" in notes
    assert "## Top ten, phase 4 keyset + covering index" in notes
    assert "FROM customers WHERE customers.id = $1" in notes
    assert "Index Only Scan using idx_orders_listing" in (tmp_path / "e3_keyset_page10000_covering.txt").read_text()
    assert len(list(tmp_path.glob("*.txt"))) == 6
```

The replay is run with `--requests 60` into a temporary folder and must exit with 0. The notes must contain the heading of the first phase's ranking and of the fourth, the per-order customer lookup statement, and the plan of the covering-index page must show an `Index Only Scan using idx_orders_listing`. Finally the folder must hold exactly six plan files: three offset plans, two keyset plans and the covering plan.

#### `tests/unit/domain/test_plan.py`

The code under test turns the text that PostgreSQL prints for `EXPLAIN (ANALYZE, BUFFERS)` into a small summary object: the execution time, the number of 8 kilobyte pages touched, the kinds of plan step (called nodes), the indexes used, how many rows a filter threw away and how many times an index-only scan had to visit the table anyway (heap fetches). The tests feed it plan text written out by hand, so no database is needed.

`tests/unit/domain/test_plan.py`, lines 1 to 4:

```python
import pytest

from busy_listing.domain.errors import PlanParseError
from busy_listing.domain.plan import pages_touched, parse_json_plan, parse_text_plan
```

`pytest` is needed for `pytest.raises`. The next line imports the error class `PlanParseError`, which the parser raises for text it cannot read. The last line imports the three functions under test: `pages_touched`, `parse_json_plan` and `parse_text_plan`.

`tests/unit/domain/test_plan.py`, lines 6 to 13:

```python
SEQ_SCAN = [
    "Seq Scan on orders  (cost=0.00..78125.01 rows=5000 width=456) (actual time=1.1..384.2 rows=2748.00 loops=1)",
    "  Filter: (date(created_at) = '2026-03-14'::date)",
    "  Rows Removed by Filter: 997252",
    "  Buffers: shared hit=47646 read=15479 written=158",
    "Planning Time: 0.042 ms",
    "Execution Time: 384.711 ms",
]
```

`SEQ_SCAN` is a list of text lines in exactly the shape PostgreSQL prints for a query that read the whole `orders` table (`Seq Scan` means sequential scan). The module-level name in capital letters is a Python convention for a constant. Reading the lines one by one: line 7 is the plan node with its estimates (`cost`, `rows`, `width`) and, in the second pair of parentheses, what really happened (`actual time` in milliseconds, `rows`, `loops`). Line 8 is the filter, which keeps only rows of one date. Line 9 says 997,252 rows were read and thrown away. Line 10 is the buffer line: `shared hit=47646` pages were found in PostgreSQL's memory cache, `read=15479` had to be fetched from the operating system, and `written=158` were written out. Line 11 is the time spent planning. Line 12 is the total execution time, which is the line the parser looks for first.

`tests/unit/domain/test_plan.py`, lines 14 to 20:

```python
INDEX_ONLY = [
    "Index Only Scan using idx_orders_listing on orders  (cost=0.42..50.02 rows=960 width=33) (actual rows=1010.00)",
    "  Heap Fetches: 0",
    "  Buffers: shared hit=506",
    "Serialization: time=0.896 ms  output=69kB  format=text",
    "Execution Time: 2.095 ms",
]
```

`INDEX_ONLY` is the plan of a query answered from an index alone. Its node line says `Index Only Scan using idx_orders_listing`, so the index name is part of the node text. `Heap Fetches: 0` says that the table itself never had to be visited, which only works when the table's pages are marked all-visible. `Buffers: shared hit=506` is the page count. The `Serialization:` line is something PostgreSQL 17 and later print when the `SERIALIZE` option is used: the time spent turning the result rows into the text sent to the client.

`tests/unit/domain/test_plan.py`, lines 21 to 27:

```python
SORT_OVER_BITMAP = [
    "Sort  (cost=3710.69..3713.21 rows=1006 width=457) (actual time=2.4..2.5 rows=1010.00 loops=1)",
    "  Buffers: shared hit=1009",
    "  ->  Bitmap Heap Scan on orders  (cost=29.48..3722.78 rows=1024 width=457) (actual time=0.1..1.9 rows=1010)",
    "        ->  Bitmap Index Scan on idx_orders_customer_created  (cost=0.00..29.23 rows=1024 width=0)",
    "Execution Time: 3.293 ms",
]
```

`SORT_OVER_BITMAP` has three nested nodes: a `Sort` on top, a `Bitmap Heap Scan` below it and a `Bitmap Index Scan` below that. The arrow `->` and the deeper indentation mark nesting. A bitmap scan first collects the locations of matching rows from an index into an in-memory bitmap and then reads the table pages in physical order. Its index name appears as `Bitmap Index Scan on idx_orders_customer_created`, a different wording from the `using` of the other scans.

`tests/unit/domain/test_plan.py`, lines 30 to 38:

```python
def test_a_sequential_scan_is_read_with_its_time_pages_and_discarded_rows():
    plan = parse_text_plan(SEQ_SCAN)
    assert plan.execution_ms == 384.711
    assert plan.pages == 47646 + 15479
    assert plan.node_types == ("Seq Scan",)
    assert plan.rows_removed_by_filter == 997252
    assert plan.heap_fetches is None
    assert plan.has_node("Seq Scan")
    assert not plan.has_node("Sort")
```

The first test parses the sequential scan and checks every field of the summary. `plan.execution_ms == 384.711` is the number from the last line. `plan.pages == 47646 + 15479` shows how pages are counted: `hit` plus `read`, and not `written`. `node_types == ("Seq Scan",)` compares with a one-item tuple. `rows_removed_by_filter == 997252` is the number from the filter line. `plan.heap_fetches is None` uses `is None` because the plan has no such line, so the value is "not reported" rather than zero. `plan.has_node("Seq Scan")` is true and `not plan.has_node("Sort")` is true, which tests the helper that looks a node type up.

`tests/unit/domain/test_plan.py`, lines 41 to 46:

```python
def test_an_index_only_scan_reports_the_index_and_zero_heap_fetches():
    plan = parse_text_plan(INDEX_ONLY)
    assert plan.index_names == ("idx_orders_listing",)
    assert plan.heap_fetches == 0
    assert plan.uses_index("idx_orders_listing")
    assert not plan.uses_index("orders_pkey")
```

The second test reads the index-only plan. `plan.index_names == ("idx_orders_listing",)` shows that the name was cut out of the `using` text. `heap_fetches == 0` is the "zero" case, which is different from `None`: a zero tells the reader the index-only scan was fully effective. `uses_index` answers yes for the name that appears and no for `orders_pkey`, which does not.

`tests/unit/domain/test_plan.py`, lines 49 to 52:

```python
def test_nested_nodes_and_bitmap_index_names_are_found():
    plan = parse_text_plan(SORT_OVER_BITMAP)
    assert plan.node_types == ("Sort", "Bitmap Heap Scan", "Bitmap Index Scan")
    assert plan.index_names == ("idx_orders_customer_created",)
```

The third test checks that indentation does not confuse the parser. The nodes must come back in the order they appear, outermost first, and the index name of the bitmap node must be found too.

`tests/unit/domain/test_plan.py`, lines 55 to 62:

```python
def test_pages_after_serialization_are_added_to_the_top_nodes_pages():
    lines = [
        "Seq Scan on t  (cost=0..1 rows=1)",
        "  Buffers: shared hit=207",
        "Serialization: time=30 ms",
        "  Buffers: shared hit=10625",
    ]
    assert pages_touched(lines) == 207 + 10625
```

The fourth test covers a detail of PostgreSQL 18: after the `Serialization:` line there can be a second `Buffers:` line for the pages touched while preparing the output (for example, reading oversized values stored out of line). The test builds a small plan inline with two buffer lines, 207 pages for the scan and 10,625 for serialization, and checks that `pages_touched` adds them. Writing the list inside the test instead of at the top of the file keeps the odd input next to the one assertion that needs it.

`tests/unit/domain/test_plan.py`, lines 65 to 67:

```python
def test_a_plan_without_analyze_is_refused():
    with pytest.raises(PlanParseError, match="Execution Time"):
        parse_text_plan(["Seq Scan on orders  (cost=0.00..1.00 rows=1 width=1)"])
```

A plan printed without `ANALYZE` has estimates but no execution time. The parser must refuse it rather than invent a zero, because a made-up number would look like a measurement. The test passes a one-line plan and checks that `PlanParseError` is raised with a message that mentions `Execution Time`.

`tests/unit/domain/test_plan.py`, lines 70 to 86:

```python
def test_json_plans_give_the_same_summary():
    document = {
        "Execution Time": 4.0,
        "Plan": {
            "Node Type": "Limit",
            "Shared Hit Blocks": 10,
            "Shared Read Blocks": 3,
            "Plans": [
                {"Node Type": "Index Scan", "Index Name": "idx_orders_customer_created", "Rows Removed by Filter": 7}
            ],
        },
    }
    plan = parse_json_plan(document)
    assert (plan.execution_ms, plan.pages) == (4.0, 13)
    assert plan.node_types == ("Limit", "Index Scan")
    assert plan.index_names == ("idx_orders_customer_created",)
    assert plan.rows_removed_by_filter == 7
```

The same plan can be printed as JSON (`EXPLAIN (FORMAT JSON)`), in which each node is a dictionary with keys like `"Node Type"`, `"Shared Hit Blocks"` and a list under `"Plans"` for its children. `document` is a hand-written dictionary of that shape: a `Limit` node with a child `Index Scan`. `Shared Hit Blocks` 10 and `Shared Read Blocks` 3 give 13 pages. The test checks that the JSON parser gives the same summary as the text parser would: time 4.0 and pages 13 compared as a pair, node types `("Limit", "Index Scan")` in tree order, the index name, and the filter count 7 found on the child node.

`tests/unit/domain/test_plan.py`, lines 89 to 94:

```python
def test_json_heap_fetches_are_reported():
    document = {
        "Execution Time": 1.0,
        "Plan": {"Node Type": "Index Only Scan", "Shared Hit Blocks": 1, "Shared Read Blocks": 0, "Heap Fetches": 0},
    }
    assert parse_json_plan(document).heap_fetches == 0
```

JSON plans report heap fetches under the key `"Heap Fetches"`. This test builds an index-only scan with value 0 and checks that zero comes through, not `None`.

`tests/unit/domain/test_plan.py`, lines 97 to 99:

```python
def test_a_json_plan_with_the_wrong_shape_is_refused():
    with pytest.raises(PlanParseError, match="unexpected JSON plan shape"):
        parse_json_plan({"Plan": {}})
```

A document without the `"Execution Time"` key does not have the shape of an `EXPLAIN` result. The parser must raise `PlanParseError` with the message `unexpected JSON plan shape`, so that a mistake in how the plan was fetched is reported clearly instead of showing up later as a missing-key error.

#### `tests/unit/infrastructure/test_sql_script.py`

PostgreSQL's driver can run only one statement at a time, but the lab's `.sql` files contain several. `split_statements` cuts a script into single statements. It must not cut at a semicolon inside a comment or inside quotes, and it must drop lines that belong to the `psql` program rather than to SQL (lines starting with a backslash).

`tests/unit/infrastructure/test_sql_script.py`, lines 1 to 5:

```python
from busy_listing.infrastructure.sql_script import split_statements


def test_statements_are_split_on_semicolons():
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]
```

The function under test and the simplest case: two statements separated by semicolons come back as two strings without their semicolons.

`tests/unit/infrastructure/test_sql_script.py`, lines 8 to 9:

```python
def test_comments_are_dropped_even_with_a_semicolon_in_them():
    assert split_statements("-- one; two\nSELECT 1; -- trailing; note\nSELECT 2;") == ["SELECT 1", "SELECT 2"]
```

SQL comments start with two hyphens and run to the end of the line. The first comment contains a semicolon (`-- one; two`), the second comes after a statement (`-- trailing; note`). Neither may split anything and neither may appear in the result. In the Python string `\n` is a line break.

`tests/unit/infrastructure/test_sql_script.py`, lines 12 to 13:

```python
def test_a_semicolon_inside_quotes_does_not_split():
    assert split_statements("SELECT 'a;b'; SELECT \"c;d\";") == ["SELECT 'a;b'", 'SELECT "c;d"']
```

A semicolon inside single quotes (a text value) or double quotes (an identifier) is part of the text. The Python string uses `\"` to put a double quote inside a double-quoted Python string; the expected list uses single quotes around the second item for the same reason.

`tests/unit/infrastructure/test_sql_script.py`, lines 16 to 17:

```python
def test_psql_meta_commands_are_not_sql():
    assert split_statements("\\set rows 5\nSELECT 1;\n\\gset\n") == ["SELECT 1"]
```

Lines like `\set rows 5` and `\gset` are commands of the `psql` program, not SQL. A driver would send them to the server and get a syntax error, so they must vanish. In Python source `"\\set"` is the way to write one real backslash.

`tests/unit/infrastructure/test_sql_script.py`, lines 20 to 21:

```python
def test_text_after_the_last_semicolon_is_ignored_like_an_empty_statement():
    assert split_statements("SELECT 1;\n  \n") == ["SELECT 1"]
```

Whitespace after the last semicolon is not a statement. The result is just the one real statement.

`tests/unit/infrastructure/test_sql_script.py`, lines 24 to 31:

```python
def test_every_repository_sql_file_that_python_runs_splits_into_complete_statements():
    import pathlib

    sql = pathlib.Path(__file__).resolve().parents[3] / "sql"
    for path in [*sorted((sql / "migrations").rglob("*.sql")), *sorted((sql / "explain").glob("*.sql"))]:
        statements = split_statements(path.read_text())
        assert statements, path.name
        assert all(not statement.endswith(";") for statement in statements)
```

The last test runs the splitter on the repository's real files. `pathlib.Path(__file__).resolve().parents[3] / "sql"` finds the `sql` folder: `__file__` is this test file, `.resolve()` makes it an absolute path, `.parents[3]` goes up four levels (the folders `infrastructure`, `unit`, `tests`, then the repository root; the index starts at zero for the immediate parent), and `/ "sql"` appends a folder name. The loop visits every file under `sql/migrations` (searched recursively with `rglob`) and every file in `sql/explain`, in sorted order so failures are reproducible. For each, `assert statements, path.name` demands at least one statement, and gives the file name as the failure message. The last line checks with `all(...)` that no statement ends with a semicolon, which would show that the splitter left one behind.

#### `tests/unit/infrastructure/test_artifacts.py`

`FileArtifactStore` writes what the replay produces, the captured plans and the results notes, into a folder.

`tests/unit/infrastructure/test_artifacts.py`, lines 1 to 13:

```python
from busy_listing.infrastructure.artifacts import FileArtifactStore


def test_a_plan_is_written_next_to_its_name(tmp_path):
    store = FileArtifactStore(tmp_path / "out")
    store.save_plan("q1_day_before", ["Seq Scan on orders", "Execution Time: 1.0 ms"])
    assert (tmp_path / "out" / "q1_day_before.txt").read_text() == "Seq Scan on orders\nExecution Time: 1.0 ms\n"


def test_the_report_is_written_as_results_md(tmp_path):
    store = FileArtifactStore(tmp_path)
    store.save_report("# Results\n")
    assert (tmp_path / "results.md").read_text() == "# Results\n"
```

The first test builds a store for the folder `out` inside `tmp_path`, a fresh empty folder that pytest creates for each test and removes afterwards. The `/` between a path and a text is `pathlib`'s way of joining path parts, so `tmp_path / "out"` is the path of a folder called `out` inside the temporary folder (the store must create it, because it does not exist yet). `save_plan("q1_day_before", [...])` stores two lines of plan text; the file `q1_day_before.txt` must exist in that folder and hold the two lines joined by `\n` with a final line break (`read_text()` reads the whole file as text). The second test saves the report text and expects the file `results.md` in the folder, with exactly the text that was given.

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

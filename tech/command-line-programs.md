# Command-line programs, exit codes and signals

## What it is

A **command-line program** is started by typing its name and some words (**arguments**) in a terminal. It reads its settings from those arguments and from **environment variables**, prints results, and ends with an **exit code**. This note explains the mechanics that make the programs in this repository behave well: argument parsing, exit codes, standard streams, and **signals** (messages that the operating system or another program sends to a running process).

## Why this repository uses it

The lab is four programs: the web service (`busy-listing-serve`), the load script (`busy-listing-load`), the replay of the whole lesson (`busy-listing-run`) and a health check (`busy-listing-health`). Their exit codes are their contract with `make`, with Docker's `HEALTHCHECK` and with the tests; the service and the replay must stop cleanly on Ctrl-C or `docker stop`.

## Where it appears

| File | Role |
|---|---|
| `interfaces/health_cli.py` | The health command. |
| `interfaces/run_cli.py` | The replay command, with `argparse`. |
| `interfaces/load_cli.py` | The load command, with `argparse`. |
| `interfaces/serve_cli.py` | The service in the foreground. |
| `interfaces/common.py` | Shared start-up that returns `None` on bad configuration. |
| `infrastructure/shutdown.py` | The signal flag. |
| `pyproject.toml` | `[project.scripts]` names the four commands. |
| `Dockerfile` | `HEALTHCHECK` uses the health command; `CMD` starts the service. |

## How it works underneath

**A process** is one running copy of a program. It has a number (the **PID**), three standard streams (input, output, error) and an exit code when it ends.

**Arguments.** The words after the program name arrive as a list of text (`sys.argv`). The standard module `argparse` turns them into named values: `parser.add_argument("--repetitions", type=int, default=5)` declares an optional argument `--repetitions N` whose text is converted to an int; `parser.parse_args(argv)` returns an object with the values, prints a usage message and exits with code 2 if something is wrong, and handles `--help` by itself.

**Exit codes.** The number a process returns to its parent: 0 means success, anything else means a problem. By common convention: 1 is a general failure, 2 is a usage or configuration error, and `128 + N` means "killed by signal N" (130 is `128 + 2`, the usual code after Ctrl-C). In Python, `sys.exit(n)` or `raise SystemExit(n)` ends the program with code `n`. A script uses `raise SystemExit(main())` so the number that `main` returns becomes the exit code.

**Where the program is started.** `python -m package.module` runs a module as the main program. A `[project.scripts]` entry creates a launcher that calls a function and exits with its result.

**Standard output and standard error.** Results go to standard output, diagnostics to standard error. A caller can capture one without the other.

**Signals.** The operating system can send a process a signal. `SIGINT` (number 2) is sent when you press Ctrl-C. `SIGTERM` (15) is the polite "please stop" that `docker stop` and process managers send. By default both kill the process at once. A program can install a **handler**, a function that runs instead: `signal.signal(signal.SIGTERM, handler)`. A handler should do very little; the common pattern is to set a **flag** that the main work checks between steps, so the program can finish the current step, release resources and exit cleanly. `threading.Event` is a thread-safe flag: `.set()` raises it, `.is_set()` reads it.

**Why graceful shutdown matters.** A program killed in the middle of an operation can leave half-done work behind. Stopping between two steps leaves a clear state.

## Walkthrough of this repository's use

### The health command

`src/busy_listing/interfaces/health_cli.py`, lines 1 to 27:

```python
"""Health command: exit 0 when PostgreSQL holds the seeded orders and pg_stat_statements.

python -m busy_listing.interfaces.health_cli
"""

from __future__ import annotations

from collections.abc import Sequence

from ..application.health import check_health
from ..infrastructure.health_probes import PostgresListingProbe
from .common import load_settings


def main(_argv: Sequence[str] | None = None) -> int:
    """Check PostgreSQL; returns 0 when healthy, 1 when not, 2 when the configuration is unusable."""
    settings = load_settings()
    if settings is None:
        return 2
    report = check_health([PostgresListingProbe(settings.postgres)])
    for result in report.results:
        print(f"{'ok' if result.ok else 'FAIL'} {result.name}: {result.detail}")
    return 0 if report.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- Lines 1 to 4: the docstring shows how to run it by hand: `python -m busy_listing.interfaces.health_cli`.
- `main(_argv=None) -> int`: the command takes no arguments (the underscore says the parameter is unused). It returns an integer exit code: `2` if the settings are unusable, `0` if healthy, `1` if not.
- `load_settings()` returns `None` after printing `configuration error: ...` (for example, if `PGPASSWORD` is not set).
- `check_health([PostgresListingProbe(settings.postgres)])` runs the probe; the loop prints one line per result: `ok postgres: 1,000,000 orders, pg_stat_statements loaded` or `FAIL postgres: ...`. The expression `'ok' if result.ok else 'FAIL'` picks the word.
- Lines 26 and 27: `if __name__ == "__main__": raise SystemExit(main())` — run as a program, the exit code is what `main` returned.

### The replay command

`src/busy_listing/interfaces/run_cli.py`, lines 1 to 69:

```python
"""Replay the lesson: the same load four times (naive, N+1 fixed, keyset, keyset + covering index), ranking each.

python -m busy_listing.interfaces.run_cli [--output-dir DIR] [--requests N]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from ..application.replay import ReplayLesson
from ..domain.errors import LabError, LessonInterruptedError
from ..infrastructure.artifacts import FileArtifactStore
from ..infrastructure.http_load import HttpLoadDriver
from ..infrastructure.lab_indexes import PostgresLabIndexes
from ..infrastructure.logging import fields
from ..infrastructure.pg_stat_statements import PgStatStatements
from ..infrastructure.shutdown import ShutdownSignal
from .common import load_settings, measure_host_load
from .service import running_service

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the replay. Exit codes: 0 done, 1 lab error, 2 bad configuration, 130 interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="where plans and results.md go (default: sql/explain)")
    parser.add_argument("--requests", type=int, default=0, help="requests per phase (default LOAD_REQUESTS)")
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    indexes = PostgresLabIndexes(settings.postgres, settings.sql_dir)
    replay = ReplayLesson(
        serve=lambda: running_service(settings),
        driver=HttpLoadDriver(
            f"http://{settings.app.host}:{settings.app.port}",
            settings.postgres,
            timeout_seconds=settings.app.http_timeout_seconds,
        ),
        statistics=PgStatStatements(settings.postgres),
        indexes=indexes,
        plans=indexes,
        store=FileArtifactStore(arguments.output_dir or settings.sql_dir / "explain"),
        requests=arguments.requests or settings.app.load_requests,
        host_load=measure_host_load(),
        progress=lambda message: logger.info(message),
        should_stop=lambda: shutdown.requested,
    )
    try:
        result = replay.run()
    except LessonInterruptedError:
        logger.warning("interrupted; the index state may be between phases, rerun to start clean")
        return 130
    except LabError as error:
        logger.error("the lesson failed", extra=fields(error=error))
        return 1
    for phase in result.phases:
        print(f"{phase.label:55} database time {phase.database_ms:9.0f} ms, {phase.statements:6} statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- `argparse.ArgumentParser(description=__doc__)` makes the parser and uses the module's docstring as the help text. `--output-dir` is converted to a `Path` (default `None`); `--requests` is an integer with default `0`, meaning "use `LOAD_REQUESTS`" (`arguments.requests or settings.app.load_requests`: `or` picks the right side when the left is 0). `parser.parse_args(argv)` reads `sys.argv` when `argv` is `None`.
- `settings = load_settings()`; `if settings is None: return 2`.
- `shutdown = ShutdownSignal(); shutdown.install()` installs the signal handlers (below).
- `indexes = PostgresLabIndexes(...)` is passed twice to `ReplayLesson`, as `indexes=indexes` and `plans=indexes`: one adapter implements both ports.
- `serve=lambda: running_service(settings)` is a function that, when called, starts the service (uvicorn note). `driver=HttpLoadDriver(f"http://{settings.app.host}:{settings.app.port}", ...)` builds the base URL with an f-string.
- `progress=lambda message: logger.info(message)` turns each progress message into a log line; `should_stop=lambda: shutdown.requested` lets the replay poll the flag between phases.
- The `try`/`except`: `LessonInterruptedError` means a signal arrived: it logs a warning and returns `130`. `LabError` logs the failure and returns `1`. Anything else would be a bug and would show a traceback with exit code 1.
- On success it prints one line per phase to **standard output**: `f"{phase.label:55} database time {phase.database_ms:9.0f} ms, {phase.statements:6} statements"` — `:55` pads the label to 55 characters, `:9.0f` right-aligns the number in 9 columns with no decimals, `:6` pads an integer to 6 columns. It returns `0`.

### The load command

`src/busy_listing/interfaces/load_cli.py`, lines 1 to 42:

```python
"""The lesson's load script on its own, against a running service (make serve in another terminal).

python -m busy_listing.interfaces.load_cli --strategy naive --requests 300
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from ..domain.listing import Strategy
from ..infrastructure.http_load import HttpLoadDriver
from .common import load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Send the load and print the median request time of each page."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=[s.value for s in Strategy], default=Strategy.NAIVE.value)
    parser.add_argument("--requests", type=int, default=0, help="requests to send (default LOAD_REQUESTS)")
    parser.add_argument("--seed", type=int, default=1)
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    strategy = Strategy.parse(arguments.strategy)
    driver = HttpLoadDriver(
        f"http://{settings.app.host}:{settings.app.port}",
        settings.postgres,
        timeout_seconds=settings.app.http_timeout_seconds,
        seed=arguments.seed,
    )
    bookmarks = driver.prepare(strategy)
    timings = driver.run(strategy, arguments.requests or settings.app.load_requests, bookmarks)
    print(f"{len(timings.requests)} requests, {timings.wall_seconds:.1f} s in total")
    for page, median in timings.median_by_page().items():
        print(f"  page {page:>6}: median {median:8.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`--strategy` uses `choices=[s.value for s in Strategy]`: argparse itself rejects any other word with exit code 2 and a usage message. `--requests` (default 0 = `LOAD_REQUESTS`) and `--seed` (default 1). `driver.prepare(strategy)` looks up the bookmarks for keyset; `driver.run(...)` sends the requests. The output: `print(f"{len(timings.requests)} requests, {timings.wall_seconds:.1f} s in total")` and one line per page with `f"  page {page:>6}: median {median:8.1f} ms"` (`:>6` right-aligns in 6 columns). The service must already be running (`make serve`).

### The service command

`src/busy_listing/interfaces/serve_cli.py`, lines 1 to 25:

```python
"""Serve the listing on APP_HOST:APP_PORT in the foreground; SIGINT and SIGTERM stop it after in-flight requests.

python -m busy_listing.interfaces.serve_cli
"""

from __future__ import annotations

from collections.abc import Sequence

import uvicorn

from .common import build_app, load_settings


def main(_argv: Sequence[str] | None = None) -> int:
    """Run until stopped; returns 2 when the configuration is unusable."""
    settings = load_settings()
    if settings is None:
        return 2
    uvicorn.run(build_app(settings), host=settings.app.host, port=settings.app.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Loads the settings (exit 2 if unusable), builds the application and hands it to uvicorn in the foreground; SIGINT and SIGTERM stop it gracefully (uvicorn note). It returns `0` after a graceful stop.

### The shutdown flag

`src/busy_listing/infrastructure/shutdown.py`, lines 1 to 29:

```python
"""Graceful shutdown: SIGINT and SIGTERM set a flag the work loops check between units of work."""

from __future__ import annotations

import signal
import threading
from types import FrameType


class ShutdownSignal:
    """A flag that SIGINT and SIGTERM set, which work loops check between units of work."""

    def __init__(self) -> None:
        self._requested = threading.Event()

    def install(self) -> None:
        """Route SIGINT and SIGTERM to `request`, so in-flight work finishes and connections close."""
        for number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(number, self._handle)

    def _handle(self, _number: int, _frame: FrameType | None) -> None:
        self.request()

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()
```

`ShutdownSignal` wraps a `threading.Event`. `install` loops over `(signal.SIGINT, signal.SIGTERM)` and calls `signal.signal(number, self._handle)`, so both signals call `_handle(number, frame)` instead of killing the process (`frame` is the place in the code that was interrupted; it is ignored). `_handle` calls `request`, which sets the event. `requested` is a property that reads it. Nothing else happens in the handler, which is exactly the safe pattern. The replay then raises `LessonInterruptedError` at its next checkpoint and the `finally` of `running_service` stops the service. (The foreground service does not use this class: uvicorn installs its own handlers.)

### Shared start-up

`src/busy_listing/interfaces/common.py`, lines 21 to 29:

```python
def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings
```

Bad configuration is a normal outcome of a command line, not a crash: print one line on standard error, return `None`, and let `main` return `2`.

## Try it yourself

1. `make up db` then `make health; echo "exit=$?"` prints `ok postgres: 1,000,000 orders, pg_stat_statements loaded` and `exit=0`.
2. `PGPASSWORD= .venv/bin/busy-listing-health; echo "exit=$?"` prints `configuration error: PGPASSWORD must be set and not empty (copy .env.example to .env)` and `exit=2`.
3. `make down` then `.venv/bin/busy-listing-health; echo "exit=$?"` (with your `.env` loaded) prints a `FAIL postgres: cannot query PostgreSQL: ...` line after a few retry warnings and `exit=1`.
4. `.venv/bin/python -m busy_listing.interfaces.run_cli --help` prints the usage with `--output-dir` and `--requests`.
5. `.venv/bin/busy-listing-load --strategy fast; echo "exit=$?"` prints `usage: busy-listing-load [-h] [--strategy {naive,batched,keyset}] [--requests REQUESTS] [--seed SEED]` and `busy-listing-load: error: argument --strategy: invalid choice: 'fast' (choose from naive, batched, keyset)`, with `exit=2` (argparse checks before the program does anything).
6. Start `make serve`, press Ctrl-C: uvicorn prints its shutdown lines and `echo $?` right after a direct run of `.venv/bin/busy-listing-serve` shows `0`. Start `.venv/bin/busy-listing-run`, press Ctrl-C: the log shows a warning that it was interrupted and `echo $?` shows `130`.

## Mistakes people make

- Doing real work inside a signal handler.
- Returning exit code 0 after an error, so scripts and CI think it worked.
- Printing errors on standard output and mixing them with results.
- Calling `sys.exit()` deep inside a library function instead of returning to `main`.
- Forgetting that `docker stop` sends SIGTERM and kills with SIGKILL after 10 seconds if the program ignores it.

**How this repository avoids them.** The handler only sets a flag. Exit codes are documented and tested (`tests/unit/interfaces/test_cli.py`). Logs go to standard error and results to standard output. `main` returns codes; only the last two lines of each module turn the return value into an exit.

## Check yourself

1. What exit code means success? *0.*
2. What does 130 mean? *The process ended because of signal 2 (Ctrl-C): 128 + 2.*
3. What is a signal handler good for? *Setting a flag that the main loop checks, so the program can stop cleanly.*
4. Why do results go to standard output and logs to standard error? *So that redirecting or piping the results does not capture the logs.*
5. What does `raise SystemExit(main())` do? *Calls `main`, then ends the program with the number it returned as the exit code.*

## Further reading

- `argparse` tutorial (3.13): https://docs.python.org/3.13/howto/argparse.html
- `signal` module: https://docs.python.org/3.13/library/signal.html ; `threading.Event`: https://docs.python.org/3.13/library/threading.html#event-objects
- POSIX exit status and signals: https://pubs.opengroup.org/onlinepubs/9699919799/utilities/V3_chap02.html#tag_18_08_02

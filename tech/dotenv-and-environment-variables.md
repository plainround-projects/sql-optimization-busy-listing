# Environment variables and the .env file

## What it is

An **environment variable** is a named piece of text that the operating system keeps for each running program: `PGPORT=55431`. A program is started with a copy of its parent's variables, and can read them. This is the usual way to give a program its **settings** (a database address, a password, a log level) without writing them into the code. The approach is called **twelve-factor configuration** ("store config in the environment").

A **`.env` file** is a plain text file with one `NAME=value` per line. It is a convenience for a developer's machine: a tool reads the file and puts the lines into the environment of the programs it starts. It must never be committed if it holds secrets; a **`.env.example`** with harmless placeholders is committed instead, and you copy it to `.env`.

## Why this repository uses it

The database address, the user, the password and the timeouts belong to the machine, not to the code. Both the Compose file and the Python programs read the same variables, so there is one place to change a port or a password.

## Where it appears

| File | What it does |
|---|---|
| `.env.example` | The committed list of variables with harmless example values. `make env` copies it to `.env` when there is no `.env`. |
| `.env` | Your local copy. Ignored by git (`.gitignore`) and by Docker builds (`.dockerignore`). |
| `Makefile` | `-include .env` and `export` read the file and pass the variables to every command. |
| `docker-compose.yml` | Uses `${PGUSER:-lab}`, `${PGPASSWORD:?...}`, `${PGDATABASE:-lab}`, `${PGPORT:-55432}`. |
| `src/busy_listing/infrastructure/settings.py` | Reads and validates all variables. |
| `.github/workflows/ci.yml` | Sets the same variables in the job's `env:` block. |
| `Dockerfile` | Sets `LAB_SQL_DIR` and `APP_HOST`; the example `docker run` passes `PGPASSWORD`. |

## How it works underneath

- A process receives its environment as a list of `NAME=value` strings when it starts. A child process gets a copy; changing a variable in the child does not change the parent's.
- In a shell, `NAME=value command` sets a variable for that one command; `export NAME=value` sets it for every later command in that shell.
- In Python, `os.environ` is a dictionary-like view of the environment; `os.environ.get("NAME", "default")` reads one with a fallback. Values are always **text**, even `5432`; the program converts and validates them.
- Two different tools read `.env` here: **Make** includes it as makefile text (`-include .env` plus `export` passes the variables on), and **Docker Compose** reads a `.env` file next to `docker-compose.yml` to fill `${NAME}` placeholders. The Python programs never read the file; they read their environment, which Make filled.
- **Validation at start-up.** A good program checks all its settings once, at the beginning, and stops with one clear message if one is missing or wrong, rather than failing later in the middle of work.
- **No secret defaults.** A password with a default value in the code is a password everyone knows. Here the password has no default: without it the program (and Compose) refuses to start.

## Walkthrough of this repository's use

The variables:

| Variable | Meaning | Default in the code |
|---|---|---|
| `PGHOST` | where PostgreSQL listens | `localhost` |
| `PGPORT` | its port | `55432` |
| `PGDATABASE` | database name | `lab` |
| `PGUSER` | user name | `lab` |
| `PGPASSWORD` | password | none: must be set |
| `PG_CONNECT_TIMEOUT_SECONDS` | how long to wait for a connection | `5` |
| `PG_STATEMENT_TIMEOUT_MS` | longest a statement may run | `60000` |
| `PG_PARALLEL_WORKERS_PER_GATHER` | parallel query workers per session | `0` |
| `APP_HOST` | address the listing service listens on | `127.0.0.1` |
| `APP_PORT` | its port | `8142` |
| `LISTING_STRATEGY` | version used when a request names none: `naive`, `batched` or `keyset` | `keyset` |
| `LOAD_REQUESTS` | requests per phase of the replay | `300` |
| `HTTP_TIMEOUT_SECONDS` | timeout of each load request | `60` |
| `DB_POOL_SIZE` | connections the ORM keeps ready | `5` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` | `INFO` |
| `LAB_SQL_DIR` | folder with the SQL files | the repository's `sql/` |

### The helper functions

`src/busy_listing/infrastructure/settings.py`, lines 1 to 39:

```python
"""Configuration from the environment, validated once at startup (twelve-factor). Secrets only from here."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.errors import UnknownStrategyError
from ..domain.listing import Strategy

_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class ConfigurationError(ValueError):
    """An environment variable is missing or has an unusable value."""


def _text(environ: Mapping[str, str], name: str, default: str | None = None) -> str:
    value = environ.get(name, default if default is not None else "").strip()
    if not value:
        raise ConfigurationError(f"{name} must be set and not empty (copy .env.example to .env)")
    return value


def _non_negative_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name, str(default)).strip()
    if not raw.isdigit():
        raise ConfigurationError(f"{name} must be a non-negative integer, got {raw!r}")
    return int(raw)


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    value = _non_negative_int(environ, name, default)
    if value < 1:
        raise ConfigurationError(f"{name} must be at least 1, got {value}")
    return value

```

- Line 13: `_LEVELS` is a set of the four allowed log levels. `ConfigurationError(ValueError)` is the one error type for bad settings. Line 10 and 11 import the `Strategy` enumeration and its error, because one setting is a strategy name.
- `_text(environ, name, default=None)`: reads the variable from the given mapping (`environ.get(name, default if default is not None else "")`), removes surrounding blanks with `.strip()`, and raises `ConfigurationError` if the result is empty. The message ends with "(copy .env.example to .env)", the fix for a missing password.
- `_non_negative_int`: takes the text (default converted with `str(default)`), checks `raw.isdigit()` (only digits 0 to 9, so no sign or decimal point), raises a clear error showing the bad value with `{raw!r}` (the `!r` shows quotes around text), and returns `int(raw)`.
- `_positive_int`: the same plus "at least 1".

### The settings classes and `from_env`

`src/busy_listing/infrastructure/settings.py`, lines 41 to 109:

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
    load_requests: int
    http_timeout_seconds: int
    pool_size: int


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the programs read from the environment. See .env.example for each variable."""

    postgres: PostgresSettings
    app: AppSettings
    sql_dir: Path
    log_level: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Read and validate the environment; raises `ConfigurationError` naming the first bad variable."""
        env = os.environ if environ is None else environ
        level = _text(env, "LOG_LEVEL", "INFO").upper()
        if level not in _LEVELS:
            raise ConfigurationError(f"LOG_LEVEL must be one of {sorted(_LEVELS)}, got {level!r}")
        try:
            strategy = Strategy.parse(_text(env, "LISTING_STRATEGY", "keyset"))
        except UnknownStrategyError as error:
            raise ConfigurationError(f"LISTING_STRATEGY: {error}") from error
        default_sql = Path(__file__).resolve().parents[3] / "sql"
        return cls(
            postgres=PostgresSettings(
                host=_text(env, "PGHOST", "localhost"),
                port=_positive_int(env, "PGPORT", 55432),
                database=_text(env, "PGDATABASE", "lab"),
                user=_text(env, "PGUSER", "lab"),
                password=_text(env, "PGPASSWORD"),
                connect_timeout_seconds=_positive_int(env, "PG_CONNECT_TIMEOUT_SECONDS", 5),
                statement_timeout_ms=_positive_int(env, "PG_STATEMENT_TIMEOUT_MS", 60_000),
                max_parallel_workers_per_gather=_non_negative_int(env, "PG_PARALLEL_WORKERS_PER_GATHER", 0),
            ),
            app=AppSettings(
                host=_text(env, "APP_HOST", "127.0.0.1"),
                port=_positive_int(env, "APP_PORT", 8142),
                default_strategy=strategy,
                load_requests=_positive_int(env, "LOAD_REQUESTS", 300),
                http_timeout_seconds=_positive_int(env, "HTTP_TIMEOUT_SECONDS", 60),
                pool_size=_positive_int(env, "DB_POOL_SIZE", 5),
            ),
            sql_dir=Path(_text(env, "LAB_SQL_DIR", str(default_sql))),
            log_level=level,
        )
```

- `PostgresSettings`, `AppSettings` and `Settings` are frozen dataclasses (dataclasses note); the password field is hidden from printing. `AppSettings.default_strategy` is a `Strategy`, not text.
- `from_env(cls, environ=None)` is a `@classmethod`: `cls` is the class itself. `env = os.environ if environ is None else environ` lets tests pass their own dictionary instead of the real environment.
- It reads `LOG_LEVEL` (`.upper()` makes `info` valid), checks it is one of the four allowed values, and raises `ConfigurationError` listing them.
- `LISTING_STRATEGY`: `Strategy.parse(...)` raises `UnknownStrategyError` for an unknown name; the `except` turns it into a `ConfigurationError("LISTING_STRATEGY: ...")` with `from error`.
- `default_sql = Path(__file__).resolve().parents[3] / "sql"` computes the default SQL folder: `__file__` is `.../src/busy_listing/infrastructure/settings.py`; `.resolve()` makes it absolute; `.parents[3]` goes up three levels (infrastructure, busy_listing, src) to the repository root; `/ "sql"` appends `sql`. In the Docker image `LAB_SQL_DIR=/app/sql` overrides it.
- Each setting is read with its function and default: `PGPORT` through `_positive_int(env, "PGPORT", 55432)`; `PG_STATEMENT_TIMEOUT_MS` defaults to `60_000` (underscores in numbers are only for readability).
- `password=_text(env, "PGPASSWORD")` has no default, so a missing or empty password raises the error and the command exits with code 2.
- The `AppSettings` block reads `APP_HOST`, `APP_PORT`, the strategy, `LOAD_REQUESTS`, `HTTP_TIMEOUT_SECONDS` and `DB_POOL_SIZE`.

### How the values reach the program

`Makefile`, lines 7 to 13:

```make
-include .env
export
PGHOST ?= localhost
PGPORT ?= 55432
PGUSER ?= lab
PGDATABASE ?= lab
APP_PORT ?= 8142
```

`-include .env` makes Make read `PGPASSWORD=...` lines; `export` hands every Make variable to the commands it starts; the `?=` lines add defaults for the connection variables and `APP_PORT`. So `make run` starts `busy-listing-run` with a complete environment. When you run a program yourself, load the file first: `set -a; . ./.env; set +a` (`set -a` exports every variable assigned afterwards; `.` reads the file as shell commands).

## Try it yourself

1. `make env` — prints `created .env from .env.example` the first time and nothing afterwards.
2. `PGPASSWORD= .venv/bin/busy-listing-health; echo "exit=$?"` — the configuration error and exit code 2.
3. `PGPORT=abc .venv/bin/busy-listing-health` (with the other variables loaded) — `configuration error: PGPORT must be a non-negative integer, got 'abc'`.
4. `.venv/bin/python -c "from busy_listing.infrastructure.settings import Settings; print(Settings.from_env({'PGPASSWORD': 'x'}))"` — prints the whole settings object with defaults and no password.
5. `LISTING_STRATEGY=fast .venv/bin/busy-listing-health` (with the other variables loaded) — `configuration error: LISTING_STRATEGY: unknown strategy 'fast'; use naive, batched or keyset`.
6. `docker compose config | grep POSTGRES_` — shows Compose's view of the three `POSTGRES_*` values after substitution.

## Mistakes people make

- Committing a `.env` with real passwords.
- Putting a default password in code "for convenience".
- Forgetting that all values are text (`"0"` is a true value in an `if` check, while the integer `0` is false).
- Spaces around `=` in a `.env` file (`NAME = value` is not the same as `NAME=value`).
- Assuming a variable set in one terminal exists in another.

**How this repository avoids them.** No secret has a default value. `.env` is ignored by git and by Docker. Every number is validated at start-up and the message names the variable. Tests pass a dictionary instead of touching the real environment.

## Check yourself

1. Why are settings read from the environment and not from code? *The same code can run in different places with different settings, and secrets never enter the repository.*
2. Is `PGPORT=55431` a number or text when the program reads it? *Text; the program must convert it.*
3. What does a `.env.example` file contain? *Placeholder values for every variable, committed to show which ones exist; the real `.env` is not committed.*
4. What does `NAME=value command` do in a shell? *Runs the command with `NAME` set to `value` for that command only.*
5. Why check all settings at start-up? *So a wrong or missing value produces one clear error right away, not a failure halfway through the work.*

## Further reading

- The Twelve-Factor App, "III. Config": https://12factor.net/config
- Python `os.environ`: https://docs.python.org/3.13/library/os.html#os.environ
- Compose `.env` files and interpolation: https://docs.docker.com/compose/how-tos/environment-variables/

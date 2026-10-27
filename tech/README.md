# Technology notes

This folder teaches every technology used in this repository, from zero, through the repository's own files. The repository finds the expensive queries of an ORM-backed web listing from `pg_stat_statements`, then fixes the N+1 and the deep offsets. You do not need to know any of the technologies in advance: each note defines its terms, explains how the technology works underneath, walks through the lines of *this* repository that use it, gives commands to try, lists common mistakes and ends with five questions.

Every note has the same nine parts: what it is, why this repository uses it, where it appears, how it works underneath, a walkthrough of this repository's use, try it yourself, mistakes people make (and how this repository avoids them), check yourself, and further reading.

Commands in the notes are run from the repository root. Where a note shows output, it was produced by running the command in this repository; numbers that depend on the machine (milliseconds, process ids, load averages) will differ on yours.

## If you have ten minutes

1. [pg-stat-statements](pg-stat-statements.md): the evidence the lesson is built on.
1. [sqlalchemy](sqlalchemy.md): where the N+1 comes from.
1. [postgresql-indexes](postgresql-indexes.md): why a deep offset is slow and keyset is not.

## The notes, in the order to read them

Read the language first, then the build and packaging tools, then the runtime pieces, then the database, then the tests and checks.

| # | Note | What it covers |
|---:|---|---|
| 1 | [bash](bash.md) | Bash and the shell: the shell commands in the Makefile, the CI file, the Dockerfile and the compose health check |
| 2 | [python](python.md) | Python: the language, and a walk through the domain, application and start-up code |
| 3 | [python-typing](python-typing.md) | Type hints: protocols (ports), generics, `TYPE_CHECKING` |
| 4 | [python-dataclasses](python-dataclasses.md) | Dataclasses: the frozen value objects used across the layers |
| 5 | [python-standard-library](python-standard-library.md) | The standard library modules the code uses (files, retries, SQL file runner...) |
| 6 | [regular-expressions](regular-expressions.md) | Regular expressions that read plans and validate settings |
| 7 | [python-threads](python-threads.md) | Threads, events and locks |
| 8 | [logging](logging.md) | Logging and the logfmt line format |
| 9 | [command-line-programs](command-line-programs.md) | Command-line programs: arguments, exit codes, signals, graceful shutdown |
| 10 | [dotenv-and-environment-variables](dotenv-and-environment-variables.md) | Environment variables, `.env` and the settings validation |
| 11 | [json](json.md) | JSON (and JSON Lines) where the code reads or writes it |
| 12 | [toml](toml.md) | TOML and `pyproject.toml`: project metadata and the settings of every tool |
| 13 | [setuptools](setuptools.md) | setuptools and packaging: how `src/` becomes an installable package with commands |
| 14 | [pip-and-venv](pip-and-venv.md) | pip, virtual environments and the hashed lock files |
| 15 | [uv](uv.md) | uv: the tool that produced the lock files |
| 16 | [make](make.md) | Make: the `Makefile` targets `up`, `db`, `run`, `test`, `lint`, `down` and the rest |
| 17 | [docker](docker.md) | Docker: the `Dockerfile`, `.dockerignore`, images and containers |
| 18 | [docker-compose](docker-compose.md) | Docker Compose: `docker-compose.yml`, which starts PostgreSQL 18 |
| 19 | [yaml](yaml.md) | YAML: the format of the compose file and the CI workflow |
| 20 | [http](http.md) | HTTP: requests, status codes, the listing's contract |
| 21 | [fastapi](fastapi.md) | FastAPI: the web layer of the listing |
| 22 | [uvicorn](uvicorn.md) | uvicorn: the server that runs the web application |
| 23 | [requests](requests.md) | requests: the HTTP client of the load script |
| 24 | [sql](sql.md) | SQL: every statement of the repository's `.sql` files |
| 25 | [psql](psql.md) | psql: the command-line client and its meta-commands |
| 26 | [postgresql](postgresql.md) | PostgreSQL: pages, MVCC, WAL, vacuum, settings, system views |
| 27 | [postgresql-indexes](postgresql-indexes.md) | PostgreSQL indexes used by the lab |
| 28 | [pg-stat-statements](pg-stat-statements.md) | The `pg_stat_statements` extension: ranking what the database ran |
| 29 | [explain-query-plans](explain-query-plans.md) | `EXPLAIN` and how to read a plan |
| 30 | [psycopg](psycopg.md) | psycopg 3: the PostgreSQL driver |
| 31 | [sqlalchemy](sqlalchemy.md) | SQLAlchemy: the ORM, lazy loading and the N+1 |
| 32 | [pytest](pytest.md) | pytest: unit, integration and end-to-end tests |
| 33 | [coverage](coverage.md) | Coverage: coverage.py and pytest-cov |
| 34 | [ruff](ruff.md) | ruff: linting and formatting |
| 35 | [mypy](mypy.md) | mypy: the strict type checker |
| 36 | [import-linter](import-linter.md) | import-linter: the dependency rule between the layers |
| 37 | [pip-audit](pip-audit.md) | pip-audit: the vulnerability check of the locked dependencies |
| 38 | [github-actions](github-actions.md) | GitHub Actions: `.github/workflows/ci.yml`, the checks run on every push |
| 39 | [git](git.md) | Git and `.gitignore` |
| 40 | [editorconfig](editorconfig.md) | EditorConfig: the editor rules of the repository |
| 41 | [markdown-and-mermaid](markdown-and-mermaid.md) | Markdown and Mermaid: the documentation files and diagrams |

## Which note explains which source file

| Source | Note |
|---|---|
| `Makefile` | [make](make.md), [bash](bash.md) |
| `Dockerfile`, `.dockerignore` | [docker](docker.md), [bash](bash.md) |
| `docker-compose.yml` | [docker-compose](docker-compose.md), [yaml](yaml.md) |
| `.github/workflows/ci.yml` | [github-actions](github-actions.md), [yaml](yaml.md) |
| `pyproject.toml` | [toml](toml.md), [setuptools](setuptools.md), [ruff](ruff.md), [mypy](mypy.md), [pytest](pytest.md), [coverage](coverage.md), [import-linter](import-linter.md) |
| `requirements.lock`, `requirements-dev.lock` | [pip-and-venv](pip-and-venv.md), [uv](uv.md), [pip-audit](pip-audit.md) |
| `.gitignore` | [git](git.md) |
| `.editorconfig` | [editorconfig](editorconfig.md) |
| `.env.example` and `.env` | [dotenv-and-environment-variables](dotenv-and-environment-variables.md) |
| `README.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `docs/adr/*.md` | [markdown-and-mermaid](markdown-and-mermaid.md) |
| `sql/*.sql`, `sql/migrations/` | [sql](sql.md), [psql](psql.md), [postgresql](postgresql.md) |
| `sql/explain/` | [explain-query-plans](explain-query-plans.md) |
| `sql/migrations/*.sql` | [postgresql-indexes](postgresql-indexes.md) |
| `src/busy_listing/domain/*.py` | [python](python.md), [python-dataclasses](python-dataclasses.md), [python-typing](python-typing.md), [regular-expressions](regular-expressions.md) |
| `src/busy_listing/application/*.py` | [python](python.md), [python-typing](python-typing.md), [python-dataclasses](python-dataclasses.md), [pg-stat-statements](pg-stat-statements.md) |
| `src/busy_listing/infrastructure/orm.py`, `sqlalchemy_orders.py` | [sqlalchemy](sqlalchemy.md) |
| `src/busy_listing/infrastructure/pg_stat_statements.py` | [pg-stat-statements](pg-stat-statements.md), [psycopg](psycopg.md) |
| `src/busy_listing/infrastructure/postgres.py`, `lab_indexes.py`, `health_probes.py` | [psycopg](psycopg.md) |
| `src/busy_listing/infrastructure/http_load.py` | [requests](requests.md), [http](http.md) |
| `src/busy_listing/infrastructure/settings.py` | [dotenv-and-environment-variables](dotenv-and-environment-variables.md), [python-dataclasses](python-dataclasses.md) |
| `src/busy_listing/infrastructure/logging.py` | [logging](logging.md) |
| `src/busy_listing/infrastructure/retry.py`, `artifacts.py`, `sql_script.py` | [python-standard-library](python-standard-library.md) |
| `src/busy_listing/infrastructure/shutdown.py`, `interfaces/*_cli.py` | [command-line-programs](command-line-programs.md) |
| `src/busy_listing/interfaces/http_app.py` | [fastapi](fastapi.md), [http](http.md), [json](json.md) |
| `src/busy_listing/interfaces/service.py`, `serve_cli.py` | [uvicorn](uvicorn.md), [python-threads](python-threads.md) |
| `tests/` | [pytest](pytest.md), [coverage](coverage.md) |

## Dependencies you do not see in the code

The lock file pins more packages than the code imports: the *dependencies of the dependencies*. This table is read from `requirements-dev.lock` (`# via` comments): each package, the version, who needs it, and the note that explains the package that needs it.

| Package | Version | Needed by | Explained in |
|---|---|---|---|
| `annotated-doc` | 0.0.5 | `fastapi` | [fastapi](fastapi.md) |
| `annotated-types` | 0.8.0 | `pydantic` | [fastapi](fastapi.md) |
| `anyio` | 4.15.1 | `httpx`, `starlette` | [fastapi](fastapi.md) |
| `ast-serialize` | 0.13.1 | `mypy` | [mypy](mypy.md) |
| `boolean-py` | 5.0 | `license-expression` | [pip-audit](pip-audit.md) |
| `cachecontrol` | 0.14.4 | `pip-audit` | [pip-audit](pip-audit.md) |
| `certifi` | 2026.10.23 | `httpcore`, `httpx`, `requests` | [fastapi](fastapi.md) |
| `charset-normalizer` | 3.5.2 | `requests` | [requests](requests.md) |
| `click` | 8.5.0 | `import-linter`, `uvicorn` | [import-linter](import-linter.md) |
| `colorama` | 0.4.6 | `pytest` | [pytest](pytest.md) |
| `coverage` | 7.17.0 | `pytest-cov` | [coverage](coverage.md) |
| `cyclonedx-python-lib` | 11.12.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `defusedxml` | 0.7.1 | `py-serializable` | [pip-audit](pip-audit.md) |
| `filelock` | 4.2.4 | `cachecontrol` | [pip-audit](pip-audit.md) |
| `grimp` | 3.18 | `import-linter` | [import-linter](import-linter.md) |
| `h11` | 0.16.0 | `httpcore`, `uvicorn` | [fastapi](fastapi.md) |
| `httpcore` | 1.0.9 | `httpx` | [fastapi](fastapi.md) |
| `idna` | 3.20 | `anyio`, `httpx`, `requests` | [fastapi](fastapi.md) |
| `iniconfig` | 2.3.1 | `pytest` | [pytest](pytest.md) |
| `librt` | 0.16.0 | `mypy` | [mypy](mypy.md) |
| `license-expression` | 30.4.4 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `markdown-it-py` | 4.2.0 | `rich` | [import-linter](import-linter.md) |
| `mdurl` | 0.1.2 | `markdown-it-py` | [import-linter](import-linter.md) |
| `msgpack` | 1.2.4 | `cachecontrol` | [pip-audit](pip-audit.md) |
| `mypy-extensions` | 1.1.0 | `mypy` | [mypy](mypy.md) |
| `opentelemetry-api` | 1.45.1 | `fastapi` | [fastapi](fastapi.md) |
| `packageurl-python` | 0.17.6 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `packaging` | 26.3 | `pip-audit`, `pip-requirements-parser`, `pytest` | [pip-audit](pip-audit.md) |
| `pathspec` | 1.1.1 | `mypy` | [mypy](mypy.md) |
| `pip` | 26.2.2 | `pip-api` | [pip-audit](pip-audit.md) |
| `pip-api` | 0.0.35 | `pip-audit` | [pip-audit](pip-audit.md) |
| `pip-requirements-parser` | 32.0.1 | `pip-audit` | [pip-audit](pip-audit.md) |
| `platformdirs` | 4.13.5 | `pip-audit` | [pip-audit](pip-audit.md) |
| `pluggy` | 1.7.0 | `pytest`, `pytest-cov` | [pytest](pytest.md) |
| `psycopg-binary` | 3.3.6 | `psycopg` | [psycopg](psycopg.md) |
| `py-serializable` | 2.1.0 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `pydantic` | 2.14.1 | `fastapi` | [fastapi](fastapi.md) |
| `pydantic-core` | 2.50.1 | `pydantic` | [fastapi](fastapi.md) |
| `pygments` | 2.21.0 | `pytest`, `rich` | [pytest](pytest.md) |
| `pyparsing` | 3.3.3 | `pip-requirements-parser` | [pip-audit](pip-audit.md) |
| `rich` | 15.0.0 | `import-linter`, `pip-audit` | [import-linter](import-linter.md) |
| `sortedcontainers` | 2.4.0 | `cyclonedx-python-lib` | [pip-audit](pip-audit.md) |
| `starlette` | 1.10.0 | `fastapi` | [fastapi](fastapi.md) |
| `tomli` | 2.5.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `tomli-w` | 1.2.0 | `pip-audit` | [pip-audit](pip-audit.md) |
| `typing-extensions` | 4.16.0 | `anyio`, `cyclonedx-python-lib`, `fastapi`, `import-linter`, `mypy`, `opentelemetry-api`, `psycopg`, `pydantic`, `pydantic-core`, `sqlalchemy`, `starlette`, `typing-inspection` | [fastapi](fastapi.md) |
| `typing-inspection` | 0.4.4 | `fastapi`, `pydantic` | [fastapi](fastapi.md) |
| `tzdata` | 2026.5 | `psycopg` | [psycopg](psycopg.md) |
| `urllib3` | 2.8.0 | `requests`, `types-requests` | [requests](requests.md) |

## Versions

Everything stated in the notes is true for the versions pinned in `requirements-dev.lock` and for PostgreSQL 18 (`postgres:18`); each note's last section links to the documentation of that version.

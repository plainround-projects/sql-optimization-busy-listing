# SQL optimization: busy listing

A small web app and ORM that lists orders with their customers, 20 to a page, a load script that clicks through pages including deep ones, and the database's own statistics (`pg_stat_statements`) used to find, fix and prove the two classic problems: an ORM's N+1 and deep offset pagination.

This repository is the runnable build of the Plainround lesson **"Fix a busy listing from the database's own statistics"** (`/prep/sql-optimization/project-busy-listing`, planned at **9 hours**). It uses PostgreSQL 18 with `pg_stat_statements`, one of the two engines the lesson allows.

## What is in it

| Piece | Where |
|---|---|
| PostgreSQL 18 with `pg_stat_statements` preloaded | `docker-compose.yml` |
| Schema (DDL), seed (DML), the queries the lesson runs by hand | `sql/001_schema.sql`, `sql/002_seed.sql`, `sql/003_queries.sql` |
| The index change as expand then contract, each step with a down script | `sql/migrations/`, `sql/migrations/down/` |
| Every plan the lesson reads (`.sql` to run, `.txt` captured) and the rankings | `sql/explain/` |
| The listing service (FastAPI, SQLAlchemy 2.0 ORM) | `src/busy_listing/interfaces/http_app.py`, `infrastructure/sqlalchemy_orders.py` |
| Load script and the replay of the whole lesson | `busy-listing-load`, `busy-listing-run` |
| Tests at three levels, one per "Done when" line | `tests/unit`, `tests/integration`, `tests/e2e` |
| How it fits together, and why | [ARCHITECTURE.md](ARCHITECTURE.md), [docs/adr/](docs/adr/) |

## Project structure

```text
.
├── src/busy_listing/         the Python package (pattern: ports and adapters in four layers)
│   ├── domain/               pure values and rules: the opaque cursor, the listing request, statement
│   │                         ranking, load timings, plan parsing, host load. No framework, no I/O.
│   ├── application/          the use cases (list one page, replay the lesson, health) and the ports
│   │                         they need (order repository, statistics, indexes, plans, load, files)
│   ├── infrastructure/       the adapters: SQLAlchemy/psycopg, pg_stat_statements, the HTTP load driver,
│   │                         files, settings, logging, retry with backoff, graceful shutdown
│   └── interfaces/           the FastAPI app, the commands (serve, load, run, health), the composition root
├── tests/
│   ├── unit/                 no database; domain and application coverage gate at 95%
│   ├── integration/          the lesson's outcomes and the adapters against PostgreSQL 18
│   └── e2e/                  the running service and the whole replay
├── sql/                      what you run by hand and what the program runs
│   ├── 001_schema.sql        002_seed.sql  003_queries.sql  reset.sql
│   ├── migrations/           001 expand (covering index), 002 contract (drop the old one); down/ for both
│   └── explain/              captured plans and results.md written by make run
├── docs/adr/                 architecture decision records
├── Dockerfile                the container image of the commands (non-root, health check)
├── docker-compose.yml        PostgreSQL 18 with pg_stat_statements preloaded
├── pyproject.toml            package, tool configuration, import-linter contracts
├── requirements.lock         hashed, pinned runtime dependencies
├── requirements-dev.lock     hashed, pinned development dependencies
├── Makefile                  up, db, run, test, lint, down (make help lists all)
├── .github/workflows/ci.yml  checks and audit; integration and end-to-end tests with a PostgreSQL 18 service
├── CHANGELOG.md  .editorconfig  .gitignore  .dockerignore  LICENSE
└── ARCHITECTURE.md  README.md
```

The dependency rule is the layer order: `interfaces` imports `infrastructure`, `infrastructure` imports `application`, `application` imports `domain`, and nothing imports the other way. `lint-imports` (part of `make lint`) fails on a violation, and a second contract keeps `psycopg`, SQLAlchemy, FastAPI, `requests` and `uvicorn` out of `domain` and `application`.

## Prerequisites

| Tool | Version used | Notes |
|---|---|---|
| Docker with Compose v2 | Docker 24 or newer | Runs PostgreSQL. No local PostgreSQL or `psql` needed. |
| Python | 3.12 or newer (tested on 3.13) | Runs the service, the load and the tests in a virtual environment (`.venv/`, built from the lock file). |
| make | any | |
| PostgreSQL | **18** (`postgres:18`) | The track assumes PostgreSQL 18 as of October 2026. `pg_stat_statements` ships with it. |

Free disk: about 1 GB. Ports: PostgreSQL on 55432, the service on 8142 (both changeable in `.env`).

## Setup, run, test, stop

```bash
cp .env.example .env   # one-time: PGPASSWORD has no default on purpose (use any throwaway value)
```

```bash
make up      # start PostgreSQL 18 on localhost:55432 and wait until it is healthy
```

```bash
make db      # schema, 100,000 customers and 1,000,000 orders (about 30 seconds the first time), the lesson's queries
```

```bash
make run     # start the service, run the same 300-request load four times, rank the queries each time (about a minute)
```

```bash
make test    # unit tests with coverage, no database needed
```

```bash
make test-integration test-e2e   # the lesson's outcomes and the adapters against the database, then the service and the replay
```

```bash
make lint    # ruff, ruff format check, mypy strict, import-linter
```

```bash
make down    # stop PostgreSQL and delete its volume
```

`make run` rewrites the plans in `sql/explain/*.txt` and `sql/explain/results.md` with your machine's numbers; the first lines of `results.md` say how busy the machine was. To use the service by hand: `make serve`, then in another terminal `curl 'http://localhost:8142/orders?strategy=naive&page=3'` or `curl 'http://localhost:8142/orders'` (the keyset version, which returns a `next_cursor` to pass back as `?cursor=`); `GET /health` is the health check. `make load STRATEGY=naive` runs the load script against a running service, `make health` exits 0 when the database holds the seeded tables and `pg_stat_statements` (1 when it does not, 2 when the settings are unusable), and `make psql` opens `psql` in the container.

## What the build does

The app has one endpoint, `GET /orders`, in three versions chosen by `?strategy=` (default `keyset`):

| Strategy | What it does | The problem it shows or fixes |
|---|---|---|
| `naive` | ORM entities, `OFFSET` paging, `order.customer.name` loads each customer lazily | The N+1: one orders query plus up to 20 customer queries per page. |
| `batched` | The same `OFFSET` query, then one `WHERE id = ANY($1)` for all customers on the page | N+1 fixed. Deep pages are still slow. |
| `keyset` | `WHERE (created_at, id) < (bookmark)` with only the listed columns, customers in one query, an opaque cursor | Every page costs the same. |

The replay (`busy-listing-run`, `make run`) resets `pg_stat_statements`, runs the same 300 requests (pages 0, 1, 2, 50, 100, 5,000 and 10,000, picked at random with a fixed seed) against each phase, and ranks statements by total time and by calls:

1. naive, 2. N+1 fixed, 3. keyset paging, 4. keyset plus the covering index (built next to the old index, then the old one dropped).

### The numbers from the committed run

**Measured on a loaded machine (load average 26.5 on 12 CPUs); rerun `make run` for clean figures.** From `sql/explain/results.md`: the machine was shared with other work, so every millisecond is several times higher than on a quiet machine. **Read the before-and-after ratios**, which survive load.

**Top by total time and top by calls, naive (phase 1).** Different statements, as the lesson requires:

| Ranking | Statement | Calls | Total ms | Mean ms |
|---|---|---:|---:|---:|
| By total time | `SELECT orders...` (`ORDER BY created_at DESC, id DESC LIMIT $1 OFFSET $2`) | 300 | 10,056 | 33.5 |
| By calls | `SELECT customers... WHERE customers.id = $1` | 6,000 | 82.5 | 0.014 |

The service only has a handful of statements, so each "top ten" lists all of them (two in phase 1, three in phase 4).

**Same load, four phases (ratio of database time, naive to final: about 300 times less):**

| Phase | Database time | Statements | Median page 1 | Median page 10,000 |
|---|---:|---:|---:|---:|
| 1 naive | 10,139 ms | 6,300 | 15.9 ms | 150.7 ms |
| 2 N+1 fixed | 8,941 ms | 600 | 3.9 ms | 112.7 ms |
| 3 keyset | 29 ms | 600 | 2.8 ms | 3.0 ms |
| 4 keyset + covering index | 33 ms | 600 | 3.8 ms | 4.0 ms |

Median page times are the request as the client sees it (HTTP, ORM, database), so they have a floor of a few milliseconds that is not the database. Database time is the sum of `total_exec_time` over all statements, so it shows only what PostgreSQL spent: 10,139 ms to 33 ms for the identical load. Fixing the N+1 on its own barely moves database time (each customer lookup costs hundredths of a millisecond); what it removes is 5,700 statements and their round trips, which is what the client waits for (the median page 1 falls from 15.9 to 3.9 ms). The deep offset is what costs the database time, and keyset paging removes it. Phases 3 and 4 differ by less than the run-to-run noise at this size; the covering index shows in the plan (pages touched), not in this table.

**Offset pagination, from the plans** (`sql/explain/e1_*.txt`):

| Page | Execution | Pages touched |
|---|---:|---:|
| 1 (`OFFSET 0`) | 0.04 ms | 23 |
| 100 (`OFFSET 1980`) | 1.1 ms | 2,010 |
| 10,000 (`OFFSET 199980`) | 189 ms | 200,751 (the scan below the `Limit` produced 200,000 rows to keep 20) |

**Keyset pagination** (`e2_*`, `e3_*`): page 1 and "page 10,000" both touch 23 pages and take well under a tenth of a millisecond; with the covering index the deep page touches 5 pages, as an `Index Only Scan` with `Heap Fetches: 0`.

## Done when: how each line is proved

| Done when (lesson) | How to see it | Test |
|---|---|---|
| **Step 1.** Your notes name the top query by total time and the top one by calls, and they are different queries. | `sql/explain/results.md`, "Top ten, phase 1": the `OFFSET` listing tops total time (300 calls, 17 ms each), the customer lookup tops calls (6,000 calls, 0.005 ms each). | `test_step1_the_top_by_total_time_and_the_top_by_calls_are_different_queries` |
| **Step 2.** A page load issues two queries or fewer, checked by a test that counts statements, and the top-by-calls query disappears from the next ranking. | The test counts statements with a SQLAlchemy `before_cursor_execute` listener: 15 or more for `naive`, at most 2 for `batched` and `keyset`. Phase 2 of `results.md` shows the per-id lookup gone; the batched lookup has 300 calls, one per page. | `test_step2_a_page_issues_two_statements_or_fewer_once_the_n_plus_one_is_fixed`, `test_step2_the_per_order_lookup_disappears_from_the_next_ranking` |
| **Step 3.** You have the three timings and a plan for page 10,000 that shows how many rows it read and discarded. | `e1_offset_page1.txt`, `e1_offset_page100.txt`, `e1_offset_page10000.txt` and the table above. In the last, the `Index Scan` under the `Limit` shows `rows=200000.00`. | `test_step3_offset_reads_and_discards_every_row_before_the_page` |
| **Step 4.** Page 10,000 takes about as long as page 1, and paging through the whole table returns every order exactly once while new orders are inserted. | `e2_keyset_page1.txt` against `e2_keyset_page10000.txt` (23 pages each). The walk test pages through all 1,000,000 orders in pages of 1,000 while a second connection inserts new, backdated and tied orders. | `test_step4_a_deep_keyset_page_costs_about_what_page_one_costs`, `test_step4_every_order_exactly_once_while_new_orders_are_inserted`, `test_step4_ties_never_split_a_page_boundary_and_the_cursor_hides_its_shape` |
| **Step 5.** The plan shows an index-only scan, or you can explain why it does not. | `e3_keyset_page10000_covering.txt`: `Index Only Scan using idx_orders_listing`, `Heap Fetches: 0`, 5 pages against 23. The migration runs `VACUUM` so the visibility map is current. | `test_step5_the_covering_index_gives_an_index_only_scan_with_no_heap_visits`, `test_step5_the_index_change_is_expand_then_contract` |
| **Step 6.** The README has the before-and-after top ten with total time, calls and mean time, and the total database time for the same load. | The phase table and the first table above; the full top-ten tables for phase 1 and phase 4 are in `sql/explain/results.md`. | `test_step6_the_same_load_costs_far_less_database_time_after_the_fixes` |
| **Common mistakes** (lesson): ties need the second column; offset pages repeat rows when data arrives. | | `test_common_mistake_a_cursor_on_created_at_alone_skips_tied_orders`, `test_common_mistake_offset_paging_repeats_a_row_when_a_new_order_arrives_between_pages` |
| **Production grade.** Every script runs twice without harm; every migration has a way back. | `sql/migrations/down/`; `make db` twice changes nothing. | `test_migrations_run_twice_and_revert_in_reverse_order_without_harm`, `test_the_seed_script_leaves_tables_that_have_rows_alone` |

## Quality bar

| Concern | How it is met |
|---|---|
| Design | Ports and adapters in four layers; the rule is enforced by import-linter. See [ARCHITECTURE.md](ARCHITECTURE.md) and [docs/adr/](docs/adr/). |
| Types, format, lint | mypy strict, ruff check and format in `make lint` and CI. |
| Tests | Unit (no database, coverage gate of 95% on domain and application, reported on every run), integration (PostgreSQL 18), end-to-end (the running service and the whole replay). |
| Logging | Structured `key=value` lines on stderr (`LOG_LEVEL` to change the level); results go to stdout and to files. |
| Health | `GET /health` (503 when PostgreSQL is not usable), `make health`, and a `HEALTHCHECK` in the container image. |
| Shutdown | SIGINT and SIGTERM stop the service and the replay at the next safe point and exit 130. |
| Timeouts and retries | Connections and statements have timeouts; connecting retries with exponential backoff and jitter; the load driver retries failed HTTP calls. |
| Secrets | Only from the environment. `PGPASSWORD` has no default; the compose file refuses to start without it. |
| Dependencies | Hashed lock files; `make audit` runs `pip-audit` on them in CI. |
| SQL | Every script runs twice without harm; each migration has a down script. |

## Stretch goals

| Stretch | Built? |
|---|---|
| Add a filter by status and decide the index column order | No. See "How to extend it" in [ARCHITECTURE.md](ARCHITECTURE.md) for the index to try (equality column first). |
| A cheaper total count than `COUNT(*)` on every page | No. |
| Slow-query logging with a threshold, and a query the statistics ranked lower than expected | No. `log_min_duration_statement` can be added to the `command` in `docker-compose.yml`. |

## What is simplified for teaching

- **Fixed request count, not five minutes.** The lesson runs the load for five minutes; this build runs 300 requests with a fixed seed, so every phase sees the identical page sequence and the rankings compare exactly. `LOAD_REQUESTS=3000 make run` makes it longer.
- **One user at a time.** The load is sequential. Concurrency would add lock waits and cache pressure the lesson does not ask about.
- **The ordering index exists from the start.** A real listing would have it, and it makes deep offset pages cost what they really cost (discarding rows) rather than a full sort. The migration replaces it with the covering index.
- **`created_at` is shuffled against `id`.** As after an import or backfill, so a page's rows are spread over many heap pages. When the two are perfectly correlated, the same page-10,000 offset costs 45 ms and 2,986 pages instead of about 90 to 110 ms and 200,751 (measured on this table); it still grows with the offset.
- **Keyset cannot jump to a page number.** The load script looks up a bookmark for each target page once, before the timed run, as a deep link or saved position would provide.
- **Cursors are opaque, not signed.** A real service would sign them.
- **Only the customer's name is shown.** The listing asks for five order columns and one customer column.
- **Throwaway credentials** (`lab`/`lab`) on a port only your machine can reach.
- **Statements are grouped by text** in the rankings, because the driver sends small and large integers with different wire types, which gives one SQL text several query ids (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## Troubleshooting

- `port is already allocated` or the app does not start: another process uses 55432 or 8142. Set `PGPORT` or `APP_PORT` in `.env`.
- `make run` or `make test` fails with a connection error: run `make up` and `make db` first.
- The `pg_stat_statements` view does not exist: the container started without the preload. Run `make down && make up && make db`.

## Author and license

Written by Sumit Srivastava. Released under the MIT License, see [LICENSE](LICENSE).

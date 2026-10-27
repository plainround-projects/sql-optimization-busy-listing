# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-27

### Added

- PostgreSQL 18 with `pg_stat_statements` preloaded in `docker-compose.yml`, run under an init process with a health check over TCP.
- SQL: an idempotent schema and a seed (100,000 customers, 1,000,000 orders with tied timestamps) that leaves populated tables alone, the lesson's queries, the covering-index change as an idempotent expand step and contract step each with a down script, a reset script, and `EXPLAIN (ANALYZE, BUFFERS)` plans as `.sql` plus captured `.txt`.
- A layered Python package (`domain`, `application`, `infrastructure`, `interfaces`) with the dependency rule enforced by import-linter: opaque keyset cursors, listing requests and the statement ranking as pure domain code, the listing and the four-phase replay as use cases over ports, SQLAlchemy and `pg_stat_statements` adapters, a FastAPI service with `/orders` and `/health`, and commands to serve, load, replay and check health.
- Unit, integration and end-to-end tests with coverage (domain and application at 100%); ruff, mypy `strict`, import-linter and `pip-audit` in CI; hashed lock files; a non-root `Dockerfile` for the service.

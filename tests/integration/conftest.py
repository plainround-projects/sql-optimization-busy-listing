"""Fixtures for the tests that need the seeded database from `make up db`."""

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from sqlalchemy import Engine, event

from busy_listing.domain.plan import PlanSummary, parse_json_plan
from busy_listing.infrastructure import postgres
from busy_listing.infrastructure.lab_indexes import PostgresLabIndexes
from busy_listing.infrastructure.orm import create_lab_engine
from busy_listing.infrastructure.pg_stat_statements import PgStatStatements
from busy_listing.infrastructure.settings import Settings
from busy_listing.infrastructure.sqlalchemy_orders import SqlAlchemyOrders


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


def explain(connection: psycopg.Connection[Any], query: str) -> tuple[PlanSummary, dict[str, Any]]:
    """The summary and the raw JSON of a query's plan with real timings and buffers."""
    document: dict[str, Any] = connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query).fetchone()[0][0]  # type: ignore[index]
    return parse_json_plan(document), document

"""Adapter: the health check of the one dependency, PostgreSQL."""

from __future__ import annotations

import psycopg

from ..application.health import ProbeFailedError
from .postgres import scalar, session
from .settings import PostgresSettings


class PostgresListingProbe:
    """Healthy when PostgreSQL answers, the orders are seeded and pg_stat_statements is loaded."""

    name = "postgres"

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def check(self) -> str:
        try:
            with session(self._settings) as connection:
                if scalar(connection, "SELECT to_regclass('public.orders')") is None:
                    raise ProbeFailedError("the orders table is missing; run make db")
                rows = scalar(connection, "SELECT count(*) FROM orders")
                extension = scalar(connection, "SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
        except psycopg.Error as error:
            raise ProbeFailedError(f"cannot query PostgreSQL: {error}") from error
        if rows == 0:
            raise ProbeFailedError("the orders table is empty; run make db")
        if extension == 0:
            raise ProbeFailedError("pg_stat_statements is not installed; run make db")
        return f"{rows:,} orders, pg_stat_statements loaded"

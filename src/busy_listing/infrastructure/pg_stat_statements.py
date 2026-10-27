"""Adapter: the database's own statistics. Implements `StatementStatistics`."""

from __future__ import annotations

from ..domain.statements import StatementStat
from .postgres import session
from .settings import PostgresSettings

# Only this database's application statements: not the ranking queries, not the extension's own calls.
_APPLICATION_STATEMENTS = """
    FROM pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND query NOT ILIKE '%pg_stat_statements%' AND query NOT ILIKE '%pg_database%'
"""


class PgStatStatements:
    """Reads and resets `pg_stat_statements`."""

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings

    def reset(self) -> None:
        with session(self._settings) as connection:
            connection.execute("SELECT pg_stat_statements_reset()")

    def snapshot(self) -> list[StatementStat]:
        with session(self._settings) as connection:
            rows = connection.execute(f"SELECT query, calls, total_exec_time {_APPLICATION_STATEMENTS}").fetchall()
        return [StatementStat(str(query), int(calls), float(total)) for query, calls, total in rows]

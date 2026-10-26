"""Rank statements from pg_stat_statements, the database's own account of what ran."""
from app.db import engine
from sqlalchemy import text

# Only this database's application statements: not the ranking queries, not the extension's own calls.
_APP_STATEMENTS = """
    FROM pg_stat_statements
    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
      AND query NOT ILIKE '%pg_stat_statements%' AND query NOT ILIKE '%pg_database%'
"""


def reset():
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_stat_statements_reset()"))


def top(order_by: str, limit: int = 10) -> list[dict]:
    """Top statements by "total_exec_time" or "calls". Rows with the same text are added together: the
    driver's prepared statements and its first few unprepared runs get different query ids in the view."""
    assert order_by in ("total_exec_time", "calls")
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT query, sum(calls)::bigint AS calls, sum(total_exec_time) AS total_exec_time, "
            f"sum(total_exec_time) / sum(calls) AS mean_exec_time {_APP_STATEMENTS} "
            f"GROUP BY query ORDER BY {order_by} DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def total_calls() -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT coalesce(sum(calls), 0) {_APP_STATEMENTS}")).scalar())


def total_database_time_ms() -> float:
    with engine.connect() as connection:
        return float(connection.execute(text(f"SELECT coalesce(sum(total_exec_time), 0) {_APP_STATEMENTS}")).scalar())

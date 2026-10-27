"""Adapter: the index state of the orders table and the plan files. Implements `IndexLayout` and `PlanCapture`."""

from __future__ import annotations

from pathlib import Path

from .postgres import session
from .settings import PostgresSettings
from .sql_script import run_file

LESSON_INDEXES = ("idx_orders_created_id", "idx_orders_listing")


class PostgresLabIndexes:
    """Moves the table between the original ordering index and the covering index, using the migration files."""

    def __init__(self, settings: PostgresSettings, sql_dir: Path) -> None:
        self._settings = settings
        self._sql_dir = sql_dir

    def migrations(self) -> list[Path]:
        """The up migrations in order."""
        return sorted((self._sql_dir / "migrations").glob("*.sql"))

    def down_migrations(self) -> list[Path]:
        """The down scripts in order."""
        return sorted((self._sql_dir / "migrations" / "down").glob("*.sql"))

    def reset_to(self, step: int) -> None:
        """Rebuild the original ordering index, then apply migrations 1 to `step`; refresh statistics."""
        with session(self._settings) as connection:
            for name in LESSON_INDEXES:
                connection.execute(f"DROP INDEX IF EXISTS {name}")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC)")
            for path in self.migrations()[:step]:
                run_file(connection, path)
            connection.execute("VACUUM ANALYZE orders")

    def capture(self, name: str) -> tuple[str, ...]:
        """Run `explain/<name>.sql` twice (the first run warms the cache) and return the second plan's lines."""
        path = self._sql_dir / "explain" / f"{name}.sql"
        with session(self._settings) as connection:
            run_file(connection, path)
            rows = run_file(connection, path)
        return tuple(row[0] for row in rows)

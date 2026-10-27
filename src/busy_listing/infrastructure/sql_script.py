"""Read the repository's SQL files and run them statement by statement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg


def split_statements(sql_text: str) -> list[str]:
    """Split SQL on semicolons, ignoring `--` comments and quoted text (enough for the files in `sql/`).

    psql meta-commands (lines starting with a backslash) are not SQL and are dropped.
    """
    lines = [line.split("--", 1)[0] for line in sql_text.splitlines() if not line.lstrip().startswith("\\")]
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for character in "\n".join(lines):
        if quote:
            quote = None if character == quote else quote
        elif character in ("'", '"'):
            quote = character
        elif character == ";":
            statements.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    return [statement for statement in statements if statement]


def run_file(connection: psycopg.Connection[Any], path: Path) -> list[Any]:
    """Run every statement of a file on one connection; return the rows of the last one that returns rows."""
    rows: list[Any] = []
    for statement in split_statements(path.read_text()):
        cursor = connection.execute(statement)
        if cursor.description:
            rows = cursor.fetchall()
    return rows

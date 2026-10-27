"""Statements as `pg_stat_statements` reports them, and how the lesson ranks them.

The view keys its rows by a query id that includes parameter types, and the driver sends an integer parameter as
`int2`, `int4` or `int8` depending on its value, so one SQL text can appear under several ids. Ranking the rows as
they are would split one statement's calls and understate it, so rows with the same text are added together.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class RankBy(StrEnum):
    """The two rankings the lesson reads: where the database spent its time, and what is asked most often."""

    TOTAL_TIME = "total_exec_time"
    CALLS = "calls"


@dataclass(frozen=True, slots=True)
class StatementStat:
    """Calls and total execution time of one statement text."""

    query: str
    calls: int
    total_ms: float

    @property
    def mean_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0

    @property
    def short(self) -> str:
        """The statement on one line, for tables."""
        return " ".join(self.query.split())


def merge_by_text(rows: Iterable[StatementStat]) -> list[StatementStat]:
    """Add together the rows that have the same query text."""
    calls: dict[str, int] = defaultdict(int)
    total: dict[str, float] = defaultdict(float)
    for row in rows:
        calls[row.query] += row.calls
        total[row.query] += row.total_ms
    return [StatementStat(query, calls[query], total[query]) for query in calls]


def rank(rows: Iterable[StatementStat], by: RankBy, limit: int = 10) -> list[StatementStat]:
    """The top `limit` statements by total time or by calls (ties keep their input order)."""
    merged = merge_by_text(rows)
    key = (lambda row: row.total_ms) if by is RankBy.TOTAL_TIME else (lambda row: float(row.calls))
    return sorted(merged, key=key, reverse=True)[:limit]


def total_time_ms(rows: Sequence[StatementStat]) -> float:
    """All the database time the statements account for."""
    return sum(row.total_ms for row in rows)


def total_calls(rows: Sequence[StatementStat]) -> int:
    """All the statements that ran."""
    return sum(row.calls for row in rows)

"""Ports: what the use cases need from the outside world. Adapters in `infrastructure` implement them."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..domain.cursor import Cursor
from ..domain.listing import PAGE_SIZE, Page, Strategy
from ..domain.load import Bookmarks, LoadTimings
from ..domain.statements import StatementStat


class OrderRepository(Protocol):
    """The three ways to read a page of orders with their customers' names."""

    def naive_page(self, page: int) -> Page:
        """OFFSET paging with one lazy customer lookup per order (the planted N+1)."""
        ...

    def batched_page(self, page: int) -> Page:
        """OFFSET paging with the page's customers fetched in one query."""
        ...

    def keyset_page(self, after: Cursor | None, page_size: int = PAGE_SIZE) -> Page:
        """The rows strictly after the bookmark, only the listed columns, customers in one query."""
        ...


class StatementStatistics(Protocol):
    """The database's own account of what ran (pg_stat_statements)."""

    def reset(self) -> None:
        """Forget everything counted so far."""
        ...

    def snapshot(self) -> list[StatementStat]:
        """Calls and total time of every application statement since the last reset."""
        ...


class IndexLayout(Protocol):
    """The indexes on orders as the lesson changes them."""

    def reset_to(self, step: int) -> None:
        """0: the original ordering index only; 2: the covering index only, after both migrations."""
        ...


class PlanCapture(Protocol):
    """Runs an `EXPLAIN (ANALYZE, BUFFERS)` file twice and returns the second plan."""

    def capture(self, name: str) -> tuple[str, ...]:
        """The measured plan's lines."""
        ...


class LoadDriver(Protocol):
    """The load script: clicks through pages the way real users do, deep pages included."""

    def prepare(self, strategy: Strategy) -> Bookmarks:
        """Look up what the strategy needs before the timed run (keyset bookmarks); outside the statistics."""
        ...

    def run(self, strategy: Strategy, requests: int, bookmarks: Bookmarks) -> LoadTimings:
        """Send `requests` listing requests with the lesson's fixed page sequence."""
        ...


class ArtifactStore(Protocol):
    """Where the replay leaves its evidence: the captured plans and the results notes."""

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        """Keep the plan next to its query."""
        ...

    def save_report(self, text: str) -> None:
        """Keep the results notes."""
        ...


class HealthProbe(Protocol):
    """A dependency's health check."""

    name: str

    def check(self) -> str:
        """Return a short description of what is healthy. Raise `ProbeFailedError` when it is not."""
        ...

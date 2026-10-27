"""In-memory stand-ins for the ports, so the use cases can be tested without a database or a server."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.listing import PAGE_SIZE, ListedOrder, Page, Strategy
from busy_listing.domain.load import Bookmarks, LoadTimings
from busy_listing.domain.statements import StatementStat

MOMENT = datetime(2026, 5, 4, 11, 2, tzinfo=UTC)


def order(order_id: int) -> ListedOrder:
    return ListedOrder(order_id, 1, "Customer 1", "paid", "10.00", MOMENT)


class FakeRepository:
    """Records which method was asked for, with what."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def naive_page(self, page: int) -> Page:
        self.calls.append(("naive", page))
        return Page((order(1),))

    def batched_page(self, page: int) -> Page:
        self.calls.append(("batched", page))
        return Page((order(2),))

    def keyset_page(self, after: Cursor | None, page_size: int = PAGE_SIZE) -> Page:
        self.calls.append(("keyset", after))
        return Page((order(3),), Cursor(MOMENT, 3))


class FakeStatistics:
    """Statements that depend on which strategy the fake driver last ran."""

    def __init__(self) -> None:
        self.resets = 0
        self.current: list[StatementStat] = []

    def reset(self) -> None:
        self.resets += 1

    def snapshot(self) -> list[StatementStat]:
        return self.current


class FakeDriver:
    """Pretends to send requests; sets what the statistics will show for the strategy."""

    def __init__(self, statistics: FakeStatistics) -> None:
        self._statistics = statistics
        self.runs: list[tuple[Strategy, int]] = []

    def prepare(self, strategy: Strategy) -> Bookmarks:
        return {0: None, 100: "cursor"} if strategy is Strategy.KEYSET else {}

    def run(self, strategy: Strategy, requests: int, bookmarks: Bookmarks) -> LoadTimings:
        self.runs.append((strategy, requests))
        heavy = strategy is not Strategy.KEYSET
        self._statistics.current = [
            StatementStat("SELECT orders OFFSET $1", requests, 5000.0 if heavy else 5.0),
            StatementStat(
                "SELECT customers WHERE id = $1", requests * 20 if strategy is Strategy.NAIVE else requests, 40.0
            ),
        ]
        return LoadTimings(((0, 3.0), (10000, 100.0 if heavy else 3.0)), 2.0)


class FakeIndexes:
    """Records the index states asked for."""

    def __init__(self) -> None:
        self.states: list[int] = []

    def reset_to(self, step: int) -> None:
        self.states.append(step)


class FakePlans:
    """Returns a plan whose time depends on the name."""

    def __init__(self) -> None:
        self.captured: list[str] = []

    def capture(self, name: str) -> tuple[str, ...]:
        self.captured.append(name)
        milliseconds = "100.0" if name.startswith("e1_offset") else "0.05"
        return (
            "Index Scan on orders  (cost=0..1 rows=1)",
            "  Buffers: shared hit=23",
            f"Execution Time: {milliseconds} ms",
        )


class RecordingStore:
    """Keeps what the replay saves."""

    def __init__(self) -> None:
        self.plans: dict[str, tuple[str, ...]] = {}
        self.report: str | None = None

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self.plans[name] = tuple(lines)

    def save_report(self, text: str) -> None:
        self.report = text


class FakeServer:
    """Counts how often the service was started and stopped."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @contextmanager
    def __call__(self) -> Iterator[None]:
        self.events.append("up")
        try:
            yield
        finally:
            self.events.append("down")

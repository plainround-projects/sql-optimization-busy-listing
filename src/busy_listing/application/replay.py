"""Use case: replay the lesson. The same load four times, ranking the database's statements each time."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from ..domain import lesson
from ..domain.errors import LessonInterruptedError
from ..domain.host import HostLoad
from ..domain.plan import PlanSummary, parse_text_plan
from ..domain.statements import RankBy, StatementStat, rank, total_calls, total_time_ms
from .ports import ArtifactStore, IndexLayout, LoadDriver, PlanCapture, StatementStatistics
from .report import render_results


@dataclass(frozen=True, slots=True)
class PhaseResult:
    """What one run of the load cost, and which statements it was made of."""

    label: str
    by_time: tuple[StatementStat, ...]
    by_calls: tuple[StatementStat, ...]
    database_ms: float
    statements: int
    wall_seconds: float
    median_ms_by_page: dict[int, float]


@dataclass(frozen=True, slots=True)
class LessonResult:
    """Everything the replay measured."""

    requests: int
    phases: tuple[PhaseResult, ...]
    plans: dict[str, PlanSummary]
    host_load: HostLoad | None = None


class ReplayLesson:
    """Drives the load and the statistics view through the lesson's four phases and keeps the evidence.

    `serve` is a context manager that keeps the listing service running while the load is sent.
    `should_stop` is polled between phases; when it returns true the replay raises `LessonInterruptedError`.
    """

    def __init__(
        self,
        *,
        serve: Callable[[], AbstractContextManager[None]],
        driver: LoadDriver,
        statistics: StatementStatistics,
        indexes: IndexLayout,
        plans: PlanCapture,
        store: ArtifactStore,
        requests: int = 300,
        host_load: HostLoad | None = None,
        progress: Callable[[str], None] = lambda _message: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        self._serve = serve
        self._driver = driver
        self._statistics = statistics
        self._indexes = indexes
        self._plans = plans
        self._store = store
        self._requests = requests
        self._host_load = host_load
        self._progress = progress
        self._should_stop = should_stop

    def run(self) -> LessonResult:
        """Run the four phases, write the plans and the notes, and return what was measured."""
        captured: dict[str, PlanSummary] = {}
        phases: list[PhaseResult] = []
        with self._serve():
            for index, phase in enumerate(lesson.PHASES):
                self._checkpoint()
                self._progress(phase.label)
                if index in (0, len(lesson.PHASES) - 1):  # the index state changes only before the first and last
                    self._indexes.reset_to(phase.index_step)
                if index == 0:
                    for name in lesson.OFFSET_PLANS:
                        self._capture(name, captured)
                phases.append(self._measure(phase))
                for name in phase.captures:
                    self._capture(name, captured)
        result = LessonResult(self._requests, tuple(phases), captured, self._host_load)
        self._store.save_report(render_results(result))
        return result

    def _measure(self, phase: lesson.Phase) -> PhaseResult:
        bookmarks = self._driver.prepare(phase.strategy)
        self._driver.run(phase.strategy, 5, bookmarks)  # warm the caches; not measured
        self._statistics.reset()
        timings = self._driver.run(phase.strategy, self._requests, bookmarks)
        rows = self._statistics.snapshot()
        result = PhaseResult(
            label=phase.label,
            by_time=tuple(rank(rows, RankBy.TOTAL_TIME)),
            by_calls=tuple(rank(rows, RankBy.CALLS)),
            database_ms=total_time_ms(rows),
            statements=total_calls(rows),
            wall_seconds=timings.wall_seconds,
            median_ms_by_page=timings.median_by_page(),
        )
        self._progress(
            f"{self._requests} requests in {result.wall_seconds:.1f} s, database time {result.database_ms:.0f} ms"
        )
        return result

    def _capture(self, name: str, captured: dict[str, PlanSummary]) -> None:
        lines = self._plans.capture(name)
        self._store.save_plan(name, lines)
        captured[name] = parse_text_plan(lines)
        self._progress(f"plan {name}: {captured[name].execution_ms:.3f} ms, {captured[name].pages} pages")

    def _checkpoint(self) -> None:
        if self._should_stop():
            raise LessonInterruptedError("stopped between phases")

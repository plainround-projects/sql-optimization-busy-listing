"""What the load script measured: how long each click took, per page."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass

#: For each page the load visits, the cursor that reaches it by keyset paging (None for the first page).
Bookmarks = Mapping[int, str | None]


@dataclass(frozen=True, slots=True)
class LoadTimings:
    """Every request of one load run as (page, milliseconds), and the wall-clock time of the run."""

    requests: tuple[tuple[int, float], ...]
    wall_seconds: float

    def median_by_page(self) -> dict[int, float]:
        """The median request time of each page that was visited."""
        by_page: dict[int, list[float]] = {}
        for page, milliseconds in self.requests:
            by_page.setdefault(page, []).append(milliseconds)
        return {page: statistics.median(values) for page, values in sorted(by_page.items())}

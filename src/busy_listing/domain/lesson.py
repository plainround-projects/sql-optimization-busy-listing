"""The lesson as data: the page sequence of the load, the phases and the plans read along the way."""

from __future__ import annotations

from dataclasses import dataclass

from .listing import Strategy

#: Pages the load visits, including genuinely deep ones. Keyset paging reaches them through bookmarks.
PAGES = (0, 1, 2, 50, 100, 5000, 10000)


@dataclass(frozen=True, slots=True)
class Phase:
    """One run of the same load: which version answers, and which index state the table is in."""

    label: str
    strategy: Strategy
    index_step: int  # 0: the ordering index only; 2: the covering index only (after both migrations)
    captures: tuple[str, ...] = ()


PHASES = (
    Phase("1 naive: offset paging, N+1 customer lookups", Strategy.NAIVE, 0),
    Phase("2 N+1 fixed: customers fetched in one query", Strategy.BATCHED, 0),
    Phase(
        "3 keyset paging on (created_at DESC, id DESC)", Strategy.KEYSET, 0, ("e2_keyset_page1", "e2_keyset_page10000")
    ),
    Phase(
        "4 keyset + covering index (expand, then contract)",
        Strategy.KEYSET,
        2,
        ("e3_keyset_page10000_covering",),
    ),
)

#: Plans read before any change: the cost of deep offsets.
OFFSET_PLANS = ("e1_offset_page1", "e1_offset_page100", "e1_offset_page10000")

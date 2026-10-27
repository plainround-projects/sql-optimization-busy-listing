"""What the listing page shows and how a client asks for it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .cursor import Cursor
from .errors import InvalidPageError, PageNumberNotSupportedError, UnknownStrategyError

PAGE_SIZE = 20


class Strategy(StrEnum):
    """The lesson's three versions of the listing."""

    NAIVE = "naive"  # OFFSET paging, one lazy customer query per order
    BATCHED = "batched"  # the same OFFSET query, customers fetched together
    KEYSET = "keyset"  # rows after a bookmark, only the listed columns

    @classmethod
    def parse(cls, name: str) -> Strategy:
        """The strategy called `name`; raises `UnknownStrategyError` for anything else."""
        try:
            return cls(name)
        except ValueError as error:
            raise UnknownStrategyError(f"unknown strategy {name!r}; use naive, batched or keyset") from error


@dataclass(frozen=True, slots=True)
class ListedOrder:
    """One row of the listing: an order and its customer's name."""

    id: int
    customer_id: int
    customer_name: str
    status: str
    total: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Page:
    """One page of orders, newest first, and the cursor of the next page when keyset paging."""

    orders: tuple[ListedOrder, ...]
    next_cursor: Cursor | None = None


@dataclass(frozen=True, slots=True)
class ListingRequest:
    """A validated request for a page. Build it with `ListingRequest.of`."""

    strategy: Strategy
    page: int
    cursor: Cursor | None

    @classmethod
    def of(cls, strategy: Strategy, page: int = 0, cursor: Cursor | None = None) -> ListingRequest:
        """Check the combination of arguments the strategy allows."""
        if page < 0:
            raise InvalidPageError(f"page must be 0 or more, got {page}")
        if strategy is Strategy.KEYSET and page:
            raise PageNumberNotSupportedError(
                "keyset paging has no page numbers: pass the cursor from the previous page"
            )
        return cls(strategy, page, cursor)

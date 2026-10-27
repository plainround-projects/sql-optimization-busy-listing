"""Use case: one page of the listing, by the strategy the caller asks for."""

from __future__ import annotations

from ..domain.listing import ListingRequest, Page, Strategy
from .ports import OrderRepository


class ListOrders:
    """Dispatches a validated request to the repository method of its strategy."""

    def __init__(self, repository: OrderRepository) -> None:
        self._repository = repository

    def __call__(self, request: ListingRequest) -> Page:
        if request.strategy is Strategy.NAIVE:
            return self._repository.naive_page(request.page)
        if request.strategy is Strategy.BATCHED:
            return self._repository.batched_page(request.page)
        return self._repository.keyset_page(request.cursor)

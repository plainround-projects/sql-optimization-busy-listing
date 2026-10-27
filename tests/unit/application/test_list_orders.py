from busy_listing.application.list_orders import ListOrders
from busy_listing.domain.listing import ListingRequest, Strategy

from .fakes import MOMENT, FakeRepository


def test_each_strategy_is_answered_by_its_repository_method():
    repository = FakeRepository()
    list_orders = ListOrders(repository)
    list_orders(ListingRequest.of(Strategy.NAIVE, page=3))
    list_orders(ListingRequest.of(Strategy.BATCHED, page=4))
    list_orders(ListingRequest.of(Strategy.KEYSET))
    assert repository.calls == [("naive", 3), ("batched", 4), ("keyset", None)]


def test_keyset_hands_back_the_next_cursor():
    page = ListOrders(FakeRepository())(ListingRequest.of(Strategy.KEYSET))
    assert page.next_cursor is not None
    assert page.next_cursor.created_at == MOMENT

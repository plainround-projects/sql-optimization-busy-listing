import pytest

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.errors import InvalidPageError, PageNumberNotSupportedError, UnknownStrategyError
from busy_listing.domain.listing import ListingRequest, Strategy


def test_a_strategy_is_found_by_its_name():
    assert [Strategy.parse(name) for name in ("naive", "batched", "keyset")] == list(Strategy)


def test_an_unknown_strategy_is_refused_with_the_choices():
    with pytest.raises(UnknownStrategyError, match="naive, batched or keyset"):
        Strategy.parse("fast")


def test_offset_strategies_take_a_page_number():
    request = ListingRequest.of(Strategy.BATCHED, page=7)
    assert (request.strategy, request.page, request.cursor) == (Strategy.BATCHED, 7, None)


def test_keyset_takes_a_cursor_not_a_page_number():
    with pytest.raises(PageNumberNotSupportedError, match="cursor"):
        ListingRequest.of(Strategy.KEYSET, page=3)
    assert ListingRequest.of(Strategy.KEYSET).page == 0


def test_a_negative_page_is_refused():
    with pytest.raises(InvalidPageError):
        ListingRequest.of(Strategy.NAIVE, page=-1)


def test_the_cursor_is_carried_through():
    from datetime import UTC, datetime

    cursor = Cursor(datetime(2026, 1, 1, tzinfo=UTC), 5)
    assert ListingRequest.of(Strategy.KEYSET, cursor=cursor).cursor == cursor

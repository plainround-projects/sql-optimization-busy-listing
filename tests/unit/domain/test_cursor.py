from datetime import UTC, datetime

import pytest

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.errors import InvalidCursorError

MOMENT = datetime(2026, 5, 4, 11, 2, 0, 123456, tzinfo=UTC)


def test_a_cursor_survives_the_round_trip_with_microseconds():
    token = Cursor(MOMENT, 832765).encode()
    assert Cursor.decode(token) == Cursor(MOMENT, 832765)


def test_the_token_does_not_show_its_shape():
    token = Cursor(MOMENT, 832765).encode()
    assert "created_at" not in token
    assert "=" not in token


@pytest.mark.parametrize("token", ["", "not base64 at all!", "e30", "eyJ0IjoiPz8iLCJpIjoxfQ"])
def test_a_token_this_service_did_not_issue_is_refused(token):
    with pytest.raises(InvalidCursorError):
        Cursor.decode(token)

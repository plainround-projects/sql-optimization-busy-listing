import pytest
from fastapi.testclient import TestClient

from busy_listing.application.health import HealthReport, ProbeResult
from busy_listing.application.list_orders import ListOrders
from busy_listing.domain.cursor import Cursor
from busy_listing.domain.listing import Strategy
from busy_listing.interfaces.http_app import create_app

from ..application.fakes import MOMENT, FakeRepository


def client(repository: FakeRepository | None = None, healthy: bool = True) -> TestClient:
    report = HealthReport((ProbeResult("postgres", healthy, "fine" if healthy else "down"),))
    return TestClient(create_app(ListOrders(repository or FakeRepository()), Strategy.KEYSET, lambda: report))


def test_the_default_strategy_answers_when_none_is_asked_for():
    repository = FakeRepository()
    body = client(repository).get("/orders").json()
    assert body["strategy"] == "keyset"
    assert repository.calls == [("keyset", None)]


def test_an_order_is_rendered_with_its_customer_and_the_next_cursor():
    body = client().get("/orders").json()
    assert body["orders"][0] == {
        "id": 3,
        "customer_id": 1,
        "customer_name": "Customer 1",
        "status": "paid",
        "total": "10.00",
        "created_at": MOMENT.isoformat(),
    }
    assert Cursor.decode(body["next_cursor"]) == Cursor(MOMENT, 3)


def test_offset_strategies_take_a_page_number():
    repository = FakeRepository()
    assert client(repository).get("/orders", params={"strategy": "batched", "page": 7}).status_code == 200
    assert repository.calls == [("batched", 7)]


def test_a_cursor_is_decoded_before_it_reaches_the_repository():
    repository = FakeRepository()
    token = Cursor(MOMENT, 99).encode()
    client(repository).get("/orders", params={"cursor": token})
    assert repository.calls == [("keyset", Cursor(MOMENT, 99))]


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"page": 3}, "cursor"),
        ({"strategy": "fast"}, "unknown strategy"),
        ({"cursor": "garbage"}, "cursor"),
        ({"strategy": "naive", "page": -1}, "page"),
    ],
)
def test_a_bad_request_is_a_400_that_says_what_to_change(params, message):
    response = client().get("/orders", params=params)
    assert response.status_code == 400
    assert message in response.json()["error"]


def test_health_is_200_when_every_check_passes_and_503_when_one_fails():
    healthy = client().get("/health")
    assert healthy.status_code == 200
    assert healthy.json()["checks"]["postgres"] == {"ok": True, "detail": "fine"}
    assert client(healthy=False).get("/health").status_code == 503

# FastAPI

## What it is

**FastAPI** is a Python **web framework**: a library for writing programs that answer HTTP requests (see the HTTP note). You write ordinary Python functions, mark them with a decorator that says "this answers `GET /orders`", and FastAPI takes care of reading the request, converting and checking its parts, and turning your return value into a JSON response. It is built on two other libraries that appear in this repository's lock file: **Starlette** (the web toolkit underneath: requests, responses, routing) and **pydantic** (checking and converting data from type hints).

## Why this repository uses it

The lesson's subject is a web listing of orders ("a small web app and ORM that lists orders with their customers, 20 to a page"). FastAPI is the thin web layer: one endpoint, `GET /orders`, in three versions chosen by a query parameter, plus `GET /health`. All the decisions about *what* to list live elsewhere (the use case); this module only translates between HTTP and those calls.

## Where it appears

| File | What it does with FastAPI |
|---|---|
| `src/busy_listing/interfaces/http_app.py` | Builds the application: the two routes and the error handler. |
| `src/busy_listing/interfaces/common.py` | `build_app` wires the use case into `create_app` (the only place that knows the real adapters). |
| `src/busy_listing/interfaces/serve_cli.py`, `service.py` | Give the application to uvicorn. |
| `tests/unit/interfaces/test_http_app.py` | Tests the routes with `TestClient`. |
| `tests/e2e/test_replay_and_service.py` | Calls the running service with `requests`. |
| `pyproject.toml` | `fastapi>=0.115` (locked at 0.162.0, with Starlette 1.10.0 and pydantic 2.14.1). |
| `domain/`, `application/` | Never import FastAPI (import-linter forbids it). |

## How it works underneath

**An application object.** `app = FastAPI(title="...")` creates the application. It does not listen on any port by itself: it is a Python object that a separate **server** program (uvicorn, see its note) calls for every request. The standard interface between the two is called **ASGI**.

**Routes.** A decorator registers a function for a method and path: `@app.get("/health")` runs the function for `GET /health`. The function is called a **path operation function**.

**Parameters come from the function signature.** A parameter that is not part of the path is read from the **query string**: `def orders(page: int = 0, cursor: str | None = None)` accepts `?page=3&cursor=abc`. The type hint is used to convert the text (`"3"` becomes the integer 3) and to reject bad values: `?page=x` is answered automatically with status **422** and a JSON description of what was wrong. A default value makes the parameter optional.

**Return values become JSON.** Returning a `dict` makes FastAPI send it as JSON with status 200. To choose the status code or the exact body, return a `JSONResponse(content, status_code=...)`.

**Plain `def` versus `async def`.** FastAPI runs a function declared with plain `def` in a pool of worker threads, so a function that waits for a database does not block the others. A function declared with `async def` runs on the server's single event loop and must only use non-blocking calls.

**Exception handlers.** `@app.exception_handler(SomeError)` registers a function that turns that kind of error, raised anywhere inside a request, into a response. The application can keep raising meaningful errors and decide in one place how they look to clients.

**Test client.** `TestClient(app)` (from `fastapi.testclient`) lets a test call the application like a client, `client.get("/orders")`, without opening a network port. It needs the `httpx` library.

**Automatic documentation.** FastAPI also serves an interactive description of the API (at `/docs`) generated from the same signatures.

## Walkthrough of this repository's use

`src/busy_listing/interfaces/http_app.py`, lines 1 to 16:

```python
"""The HTTP interface: `GET /orders` and `GET /health`. Translates requests into use-case calls and errors into 400s."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ..application.health import HealthReport
from ..application.list_orders import ListOrders
from ..domain.cursor import Cursor
from ..domain.errors import LabError
from ..domain.listing import ListingRequest, Page, Strategy

```

The docstring says what the module does. `from fastapi import FastAPI` is the application class; `from fastapi.responses import JSONResponse` lets a function choose the status code and body. The other imports are the layers below: the health report type, the use case `ListOrders`, the `Cursor` and the request types. Because this file is in `interfaces/`, it may import from `application/` and `domain/`.

`src/busy_listing/interfaces/http_app.py`, lines 18 to 33:

```python
def _body(strategy: Strategy, page: Page) -> dict[str, Any]:
    return {
        "strategy": strategy.value,
        "orders": [
            {
                "id": order.id,
                "customer_id": order.customer_id,
                "customer_name": order.customer_name,
                "status": order.status,
                "total": order.total,
                "created_at": order.created_at.isoformat(),
            }
            for order in page.orders
        ],
        "next_cursor": page.next_cursor.encode() if page.next_cursor else None,
    }
```

`_body(strategy, page)` turns a `Page` (a domain value) into the plain dictionary that becomes the JSON answer: the strategy name, a list with one small dictionary per order (a **list comprehension** over `page.orders`) and `next_cursor`, the opaque token of the next page, or `None`, which becomes JSON `null`. `order.created_at.isoformat()` writes the time as text such as `2026-05-04T11:02:00+00:00`, because JSON has no date type. `order.total` is already text (`"10.00"`), because the domain keeps money as exact text rather than a float.

`src/busy_listing/interfaces/http_app.py`, lines 36 to 56:

```python
def create_app(list_orders: ListOrders, default_strategy: Strategy, health: Callable[[], HealthReport]) -> FastAPI:
    """Build the application around its use case and its health check; nothing here reaches the database."""
    app = FastAPI(title="Busy listing")

    @app.exception_handler(LabError)
    async def refuse(_request: object, error: LabError) -> JSONResponse:
        return JSONResponse({"error": str(error)}, status_code=400)

    @app.get("/health")
    def health_endpoint() -> JSONResponse:
        report = health()
        body = {"healthy": report.healthy, "checks": {r.name: {"ok": r.ok, "detail": r.detail} for r in report.results}}
        return JSONResponse(body, status_code=200 if report.healthy else 503)

    @app.get("/orders")
    def orders(page: int = 0, cursor: str | None = None, strategy: str | None = None) -> dict[str, Any]:
        chosen = Strategy.parse(strategy) if strategy else default_strategy
        request = ListingRequest.of(chosen, page, Cursor.decode(cursor) if cursor else None)
        return _body(chosen, list_orders(request))

    return app
```

- `create_app(list_orders, default_strategy, health)` is a **factory function**: it builds and returns the application, receiving everything it needs as arguments. Nothing at import time opens a connection, which is why tests can create an app with fakes. `health: Callable[[], HealthReport]` is a function the app calls to check the database.
- `app = FastAPI(title="Busy listing")` creates the application object; the title appears in the automatic documentation.
- `@app.exception_handler(LabError)` registers `refuse` for every error of the package's base error class (`LabError`: invalid cursor, unknown strategy, page number not supported, invalid page). The handler is `async def` because it only builds a response, which is instant. It returns `JSONResponse({"error": str(error)}, status_code=400)`: a 400 answer whose message says what to change. So the use case and the domain can simply raise meaningful errors and the HTTP meaning is decided here, in one place.
- `@app.get("/health")` registers `health_endpoint` (plain `def`, so FastAPI runs it in a worker thread; it talks to the database). It calls `health()`, builds a body with `healthy` and one entry per check, and answers `200` when healthy and `503` otherwise.
- `@app.get("/orders")` registers `orders(page: int = 0, cursor: str | None = None, strategy: str | None = None)`. All three parameters come from the query string. `page` is converted to an integer by FastAPI (`?page=x` never reaches the function: FastAPI answers 422). `cursor` and `strategy` are optional text.
- The body: `chosen = Strategy.parse(strategy) if strategy else default_strategy` picks the version (an unknown name raises `UnknownStrategyError`, which `refuse` turns into 400). `ListingRequest.of(chosen, page, Cursor.decode(cursor) if cursor else None)` builds a validated request (domain rules: negative page, page number with keyset). `list_orders(request)` runs the use case, and `_body(...)` returns the dictionary, which FastAPI sends as JSON.
- `return app`.

### Wiring

`src/busy_listing/interfaces/common.py`, lines 32 to 40:

```python
def build_app(settings: Settings) -> FastAPI:
    """Wire the use case to its adapters: the one place that knows which implementations are in use."""
    engine = create_lab_engine(settings.postgres, settings.app.pool_size)
    probe = PostgresListingProbe(settings.postgres)
    return create_app(
        ListOrders(SqlAlchemyOrders(engine)),
        settings.app.default_strategy,
        lambda: check_health([probe]),
    )
```

`build_app(settings)` is the **composition root**: it creates the SQLAlchemy engine, the health probe, wraps the repository in the `ListOrders` use case and passes it with the default strategy (`LISTING_STRATEGY`, default `keyset`) and a function that runs the health check. It is the one place where "which implementations are in use" is decided.

### The routes under test

`tests/unit/interfaces/test_http_app.py`, lines 1 to 23:

```python
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

```

`client(...)` builds a real app around a fake repository (`FakeRepository` records which method was called) and returns a `TestClient`. `client(repository).get("/orders").json()` calls the route in-process and decodes the JSON. The tests check that the default strategy answers, that parameters reach the repository decoded, that bad requests give 400 with a message, and that `/health` is 200 or 503.

## Try it yourself

The service can be run without a database by giving it the same fake repository the unit tests use. Create a scratch file `/tmp/fakeserve.py`:

```python
import uvicorn
from busy_listing.application.health import HealthReport, ProbeResult
from busy_listing.application.list_orders import ListOrders
from busy_listing.domain.listing import Strategy
from busy_listing.interfaces.http_app import create_app
from tests.unit.application.fakes import FakeRepository

report = HealthReport((ProbeResult("postgres", True, "fake database"),))
uvicorn.run(create_app(ListOrders(FakeRepository()), Strategy.KEYSET, lambda: report), port=8999, log_level="warning")
```

1. In one terminal: `PYTHONPATH=. .venv/bin/python /tmp/fakeserve.py` (it keeps running; stop it with Ctrl-C).
2. In another: `curl -i "http://127.0.0.1:8999/orders"` prints `HTTP/1.1 200 OK` with `server: uvicorn`, `content-type: application/json` and a body like `{"strategy":"keyset","orders":[{"id":3,"customer_id":1,"customer_name":"Customer 1","status":"paid","total":"10.00","created_at":"2026-05-04T11:02:00+00:00"}],"next_cursor":"eyJ0Ijoi..."}`.
3. `curl -i "http://127.0.0.1:8999/orders?page=3"` prints `HTTP/1.1 400 Bad Request` and `{"error":"keyset paging has no page numbers: pass the cursor from the previous page"}`.
4. `curl -i "http://127.0.0.1:8999/orders?page=x"` prints `HTTP/1.1 422 Unprocessable Content` and `{"detail":[{"type":"int_parsing","loc":["query","page"],"msg":"Input should be a valid integer, unable to parse string as an integer","input":"x"}]}`: FastAPI's own check, before the function runs.
5. `curl "http://127.0.0.1:8999/health"` prints `{"healthy":true,"checks":{"postgres":{"ok":true,"detail":"fake database"}}}`.
6. `curl "http://127.0.0.1:8999/orders?strategy=fast"` prints `{"error":"unknown strategy 'fast'; use naive, batched or keyset"}`.
7. With the real database: `make up db`, `make serve`, and `curl "http://localhost:8142/orders?strategy=naive&page=3"`. Open `http://localhost:8142/docs` in a browser to see the automatic interactive documentation.

## Mistakes people make

- Doing blocking work (a database call) inside an `async def` function, which stalls every request.
- Letting internal errors reach the client as a 500 with a traceback, instead of mapping known errors to 4xx answers.
- Forgetting that query parameters arrive as text and need hints.
- Building the application at import time with global state, which makes it hard to test.
- Returning ORM objects directly instead of a plain, explicit body.

**How this repository avoids them.** Routes do no database work themselves; the app is built by a factory with its collaborators passed in; known errors become 400 answers with a helpful message; blocking work is in plain `def` functions (run in worker threads); the body is built explicitly in `_body`, not by returning ORM objects; the import-linter contract keeps FastAPI out of the inner layers.

## Check yourself

1. Does `FastAPI(...)` open a network port? *No; a server such as uvicorn runs the application object.*
2. What happens for `GET /orders?page=x` when `page: int` is declared? *FastAPI answers 422 and describes the invalid value; the function is not called.*
3. Where do the parameters of a `def orders(page: int = 0)` function come from? *The query string of the request.*
4. What does an exception handler do? *Turns a chosen kind of error raised during a request into a specific response.*
5. Why does `TestClient` help? *Tests can call the application without a network or a running server.*

## Further reading

- FastAPI documentation (0.162): https://fastapi.tiangolo.com/ — "Query Parameters", "Handling Errors", "Testing", "Concurrency and async / await".
- Starlette: https://www.starlette.io/ ; pydantic: https://docs.pydantic.dev/

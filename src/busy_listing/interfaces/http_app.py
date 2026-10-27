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

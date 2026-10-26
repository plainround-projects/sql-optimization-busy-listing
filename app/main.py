"""GET /orders: one listing page. The strategy decides which of the lesson's three versions answers."""
import os

from fastapi import Depends, FastAPI, HTTPException

from app import listing
from app.db import SessionFactory

app = FastAPI(title="Busy listing")


def session_per_request():
    with SessionFactory() as session:
        yield session


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/orders")
def orders(page: int = 0, cursor: str | None = None, strategy: str | None = None,
           session=Depends(session_per_request)):
    chosen = strategy or os.environ.get("LISTING_STRATEGY", "keyset")
    if chosen == "naive":
        rows, next_cursor = listing.list_orders_naive(session, page)
    elif chosen == "batched":
        rows, next_cursor = listing.list_orders_batched(session, page)
    elif chosen == "keyset":
        if page:
            raise HTTPException(400, "keyset paging has no page numbers: pass the cursor from the previous page")
        rows, next_cursor = listing.list_orders_keyset(session, cursor)
    else:
        raise HTTPException(400, f"unknown strategy {chosen!r}")
    return {"strategy": chosen, "orders": rows, "next_cursor": next_cursor}

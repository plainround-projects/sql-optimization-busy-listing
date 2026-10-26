"""The three ways the lesson lists orders with their customers, 20 to a page.

naive    ORM entities, OFFSET paging, one lazy customer query per order (the planted N+1)
batched  the same OFFSET query, customers fetched together in one query
keyset   rows after a bookmark, only the listed columns, customers fetched together (the final version)
"""
from sqlalchemy import Integer, any_, bindparam, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app import cursor
from app.models import Customer, Order

PAGE_SIZE = 20
NEWEST_FIRST = (Order.created_at.desc(), Order.id.desc())


def _row(order_id, customer_id, customer_name, status, total, created_at):
    return {"id": order_id, "customer_id": customer_id, "customer_name": customer_name,
            "status": status, "total": str(total), "created_at": created_at.isoformat()}


def _customer_names(session: Session, customer_ids) -> dict[int, str]:
    """One query for every customer on the page: `id = ANY($1)` keeps a single statement shape for any page."""
    ids = bindparam("ids", sorted(set(customer_ids)), type_=ARRAY(Integer))
    return dict(session.execute(select(Customer.id, Customer.name).where(Customer.id == any_(ids))).all())


def list_orders_naive(session: Session, page: int, page_size: int = PAGE_SIZE):
    orders = session.scalars(
        select(Order).order_by(*NEWEST_FIRST).offset(page * page_size).limit(page_size)).all()
    return [_row(o.id, o.customer_id, o.customer.name, o.status, o.total, o.created_at) for o in orders], None


def list_orders_batched(session: Session, page: int, page_size: int = PAGE_SIZE):
    orders = session.scalars(
        select(Order).order_by(*NEWEST_FIRST).offset(page * page_size).limit(page_size)).all()
    names = _customer_names(session, [o.customer_id for o in orders])
    return [_row(o.id, o.customer_id, names[o.customer_id], o.status, o.total, o.created_at) for o in orders], None


def list_orders_keyset(session: Session, after: str | None = None, page_size: int = PAGE_SIZE):
    """Orders strictly after the bookmark, newest first. Returns (rows, cursor for the next page or None)."""
    statement = select(Order.id, Order.customer_id, Order.status, Order.total, Order.created_at)
    if after:
        last_created_at, last_id = cursor.decode(after)
        statement = statement.where(tuple_(Order.created_at, Order.id) < tuple_(last_created_at, last_id))
    rows = session.execute(statement.order_by(*NEWEST_FIRST).limit(page_size)).all()
    names = _customer_names(session, [row.customer_id for row in rows])
    listing = [_row(row.id, row.customer_id, names[row.customer_id], row.status, row.total, row.created_at)
               for row in rows]
    next_cursor = cursor.encode(rows[-1].created_at, rows[-1].id) if len(rows) == page_size else None
    return listing, next_cursor

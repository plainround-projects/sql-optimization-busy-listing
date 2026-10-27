"""Adapter: the three listings with SQLAlchemy. Implements `OrderRepository`."""

from __future__ import annotations

from sqlalchemy import Engine, Integer, any_, bindparam, select, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, sessionmaker

from ..domain.cursor import Cursor
from ..domain.listing import PAGE_SIZE, ListedOrder, Page
from .orm import Customer, Order

_NEWEST_FIRST = (Order.created_at.desc(), Order.id.desc())


class SqlAlchemyOrders:
    """Reads pages of orders; one session per call, closed afterwards."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def naive_page(self, page: int) -> Page:
        """Entities by OFFSET; `order.customer.name` loads each customer lazily: one statement per order."""
        with self._sessions() as session:
            orders = session.scalars(select(Order).order_by(*_NEWEST_FIRST).offset(page * PAGE_SIZE).limit(PAGE_SIZE))
            return Page(
                tuple(
                    ListedOrder(o.id, o.customer_id, o.customer.name, o.status, str(o.total), o.created_at)
                    for o in orders.all()
                )
            )

    def batched_page(self, page: int) -> Page:
        """The same OFFSET query, then the page's customers in one `id = ANY($1)` query."""
        with self._sessions() as session:
            orders = session.scalars(
                select(Order).order_by(*_NEWEST_FIRST).offset(page * PAGE_SIZE).limit(PAGE_SIZE)
            ).all()
            names = self._customer_names(session, [o.customer_id for o in orders])
            return Page(
                tuple(
                    ListedOrder(o.id, o.customer_id, names[o.customer_id], o.status, str(o.total), o.created_at)
                    for o in orders
                )
            )

    def keyset_page(self, after: Cursor | None, page_size: int = PAGE_SIZE) -> Page:
        """Rows strictly after the bookmark; only the listed columns, so a covering index can answer alone."""
        statement = select(Order.id, Order.customer_id, Order.status, Order.total, Order.created_at)
        if after is not None:
            statement = statement.where(tuple_(Order.created_at, Order.id) < tuple_(after.created_at, after.order_id))
        with self._sessions() as session:
            rows = session.execute(statement.order_by(*_NEWEST_FIRST).limit(page_size)).all()
            names = self._customer_names(session, [row.customer_id for row in rows])
            listing = tuple(
                ListedOrder(r.id, r.customer_id, names[r.customer_id], r.status, str(r.total), r.created_at)
                for r in rows
            )
            last = rows[-1] if len(rows) == page_size else None
            return Page(listing, Cursor(last.created_at, last.id) if last else None)

    @staticmethod
    def _customer_names(session: Session, customer_ids: list[int]) -> dict[int, str]:
        """One query for every customer on the page: `id = ANY($1)` keeps a single statement shape for any page."""
        ids = bindparam("ids", sorted(set(customer_ids)), type_=ARRAY(Integer))
        return {
            row.id: row.name
            for row in session.execute(select(Customer.id, Customer.name).where(Customer.id == any_(ids)))
        }

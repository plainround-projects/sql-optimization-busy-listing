"""Adapter: the ORM mapping and the SQLAlchemy engine. `Order.customer` is lazy on purpose (the planted N+1)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Engine, ForeignKey, Numeric, Text, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .settings import PostgresSettings


class Base(DeclarativeBase):
    """Declarative base of the lab's tables."""


class Customer(Base):
    """A customer (table `customers`)."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column()


class Order(Base):
    """An order (table `orders`). Touching `order.customer` runs one SELECT per order."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    status: Mapped[str] = mapped_column(Text)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    created_at: Mapped[datetime] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)

    customer: Mapped[Customer] = relationship()


def create_lab_engine(settings: PostgresSettings, pool_size: int) -> Engine:
    """An engine with a connect timeout, a statement timeout and parallel query off for plans that read the same."""
    url = URL.create(
        "postgresql+psycopg",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
    )
    return create_engine(
        url,
        pool_size=pool_size,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.connect_timeout_seconds,
            "options": (
                f"-c statement_timeout={settings.statement_timeout_ms} "
                f"-c max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather}"
            ),
        },
    )

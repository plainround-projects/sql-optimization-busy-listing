# 0001. The N+1 is an adapter behavior, not a domain concept

Status: accepted, 2026-10-27

## Context

The lesson plants an N+1 on purpose: an ORM loads 20 orders and then one customer per order. A layered design raises the question where that belongs. If the use case knew about "lazy loading", the domain would know about the ORM.

## Decision

The use case (`ListOrders`) and the `OrderRepository` port know three things: a page by number the naive way, a page by number with the customers fetched together, and a page after a cursor. Which of them issues one statement per order is entirely inside `infrastructure/sqlalchemy_orders.py`, where `order.customer.name` triggers the lazy load. The statement count is therefore asserted in an integration test against the real engine, not in a unit test with a fake.

## Consequences

- Domain and application tests cannot demonstrate the N+1; they check dispatch and validation. The integration tests count real statements through a SQLAlchemy event listener.
- Swapping the ORM for a different one means writing a new adapter with the same three methods; nothing else changes.
- The cursor (`domain/cursor.py`) is a value object with its own encoding, so the HTTP interface, the repository and the load script share one definition.

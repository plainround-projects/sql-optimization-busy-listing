"""One test per "Done when" line of the lesson, against the seeded database (make up db first)."""

import pathlib
import threading
import time
from datetime import UTC, datetime

import pytest

from busy_listing.domain.cursor import Cursor
from busy_listing.domain.lesson import PAGES
from busy_listing.domain.statements import RankBy, rank, total_time_ms
from busy_listing.infrastructure.http_load import HttpLoadDriver
from busy_listing.infrastructure.postgres import session

from .conftest import explain

pytestmark = pytest.mark.integration

OFFSET_PAGE = "SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET {offset}"
KEYSET_PAGE = (
    "SELECT id, customer_id, status, total, created_at FROM orders WHERE (created_at, id) < ('{moment}', {order_id}) "
    "ORDER BY created_at DESC, id DESC LIMIT 20"
)
FIRST_PAGE = "SELECT id, customer_id, status, total, created_at FROM orders ORDER BY created_at DESC, id DESC LIMIT 20"
SQL = pathlib.Path(__file__).resolve().parents[2] / "sql"


def bookmark(connection, page):
    created_at, order_id = connection.execute(
        "SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1", (page * 20 - 1,)
    ).fetchone()
    return created_at, order_id


def keyset_query(connection, page):
    created_at, order_id = bookmark(connection, page)
    return KEYSET_PAGE.format(moment=created_at.isoformat(), order_id=order_id)


def run_load(repository, strategy, pages=40):
    for index in range(pages):
        page = PAGES[index % len(PAGES)]
        if strategy == "naive":
            repository.naive_page(page)
        else:
            repository.batched_page(page)


def test_step1_the_top_by_total_time_and_the_top_by_calls_are_different_queries(orders, statistics, indexes):
    statistics.reset()
    run_load(orders, "naive")
    rows = statistics.snapshot()
    by_time, by_calls = rank(rows, RankBy.TOTAL_TIME)[0], rank(rows, RankBy.CALLS)[0]
    assert "FROM orders" in by_time.query
    assert "OFFSET" in by_time.query
    assert "FROM customers WHERE customers.id = $1" in by_calls.short
    assert by_time.query != by_calls.query
    assert by_calls.calls >= 15 * by_time.calls, "a cheap statement run once per order, per page"
    assert by_time.mean_ms > 100 * by_calls.mean_ms


def test_step2_a_page_issues_two_statements_or_fewer_once_the_n_plus_one_is_fixed(orders, statement_counter):
    orders.naive_page(5)
    assert statement_counter.count >= 15, "one orders query plus one customer query per order"
    for fetch in (lambda: orders.batched_page(5), lambda: orders.keyset_page(None)):
        before = statement_counter.count
        fetch()
        assert statement_counter.count - before <= 2


def test_step2_the_per_order_lookup_disappears_from_the_next_ranking(orders, statistics, indexes):
    statistics.reset()
    run_load(orders, "batched", pages=20)
    ranked = rank(statistics.snapshot(), RankBy.CALLS)
    assert not any("customers.id = $1" in row.short for row in ranked)
    lookup = next(row for row in ranked if "= ANY" in row.short)
    assert lookup.calls == 20, "one customer query per page load"


def test_step3_offset_reads_and_discards_every_row_before_the_page(connection, indexes):
    plans = {offset: explain(connection, OFFSET_PAGE.format(offset=offset)) for offset in (0, 1980, 199980)}
    deep_summary, deep_json = plans[199980]
    assert deep_json["Plan"]["Node Type"] == "Limit"
    assert deep_json["Plan"]["Actual Rows"] == 20
    assert deep_json["Plan"]["Plans"][0]["Actual Rows"] == 199_980 + 20, "200,000 rows produced to keep 20"
    assert plans[0][0].pages < plans[1980][0].pages < deep_summary.pages
    assert deep_summary.execution_ms > 20 * plans[0][0].execution_ms


def test_step4_a_deep_keyset_page_costs_about_what_page_one_costs(connection, indexes):
    first, _ = explain(connection, FIRST_PAGE)
    deep, _ = explain(connection, keyset_query(connection, 10000))
    deep_offset, _ = explain(connection, OFFSET_PAGE.format(offset=199980))
    assert abs(deep.pages - first.pages) <= 10
    assert deep_offset.pages > 1000 * deep.pages
    assert deep.execution_ms * 20 < deep_offset.execution_ms


def test_step4_ties_never_split_a_page_boundary_and_the_cursor_hides_its_shape(orders, connection):
    expected = [
        row[0] for row in connection.execute("SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 11")
    ]
    walked, cursor = [], None
    for _ in range(6):  # pages of 2 cross the groups of three equal timestamps
        page = orders.keyset_page(cursor, page_size=2)
        walked += [order.id for order in page.orders]
        cursor = page.next_cursor
    assert walked[:11] == expected
    assert cursor is not None
    assert "created_at" not in cursor.encode()
    assert Cursor.decode(cursor.encode()) == cursor


def test_step4_every_order_exactly_once_while_new_orders_are_inserted(orders, connection, settings):
    highest_id = connection.execute("SELECT max(id) FROM orders").fetchone()[0]
    stop = threading.Event()

    def insert_orders() -> None:
        with session(settings.postgres) as writer:
            while not stop.is_set():
                writer.execute(
                    "INSERT INTO orders (customer_id, status, total, created_at) VALUES "
                    "(1, 'paid', 1, '2027-01-01'), (2, 'paid', 1, '2026-03-01 00:00:00+00'), "
                    "(3, 'paid', 1, '2026-03-01 00:00:00+00')"
                )
                time.sleep(0.002)

    writer_thread = threading.Thread(target=insert_orders)
    writer_thread.start()
    walked, cursor = [], None
    try:
        while True:
            page = orders.keyset_page(cursor, page_size=1000)
            walked += [order.id for order in page.orders]
            cursor = page.next_cursor
            if cursor is None:
                break
    finally:
        stop.set()
        writer_thread.join()
        inserted = connection.execute("SELECT count(*) FROM orders WHERE id > %s", (highest_id,)).fetchone()[0]
        connection.execute("DELETE FROM orders WHERE id > %s", (highest_id,))
    assert inserted > 0, "the writer really ran during the walk"
    assert len(walked) == len(set(walked)), "no order appeared twice"
    assert set(range(1, highest_id + 1)) <= set(walked), "no existing order was skipped"


def test_common_mistake_offset_paging_repeats_a_row_when_a_new_order_arrives_between_pages(orders, connection):
    first = [order.id for order in orders.batched_page(0).orders]
    connection.execute(
        "INSERT INTO orders (customer_id, status, total, created_at) VALUES (1, 'paid', 1, '2027-01-01')"
    )
    try:
        second = [order.id for order in orders.batched_page(1).orders]
    finally:
        connection.execute("DELETE FROM orders WHERE created_at = '2027-01-01'")
    assert first[-1] in second, "the last row of page 1 is shown again as the first row of page 2"


def test_common_mistake_a_cursor_on_created_at_alone_skips_tied_orders(connection):
    expected = [
        row[0] for row in connection.execute("SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 12")
    ]
    walked, last_created_at = [], None
    for _ in range(6):
        where = "WHERE created_at < %s" if last_created_at else ""
        rows = connection.execute(
            f"SELECT id, created_at FROM orders {where} ORDER BY created_at DESC, id DESC LIMIT 2",
            (last_created_at,) if last_created_at else (),
        ).fetchall()
        walked += [row[0] for row in rows]
        last_created_at = rows[-1][1]
    assert walked != expected[: len(walked)], "tied rows at the page boundaries were skipped"


def test_step5_the_covering_index_gives_an_index_only_scan_with_no_heap_visits(connection, indexes):
    query = keyset_query(connection, 10000)
    heap_path, _ = explain(connection, query)
    indexes.reset_to(2)
    covering, _ = explain(connection, query)
    assert covering.has_node("Index Only Scan")
    assert covering.uses_index("idx_orders_listing")
    assert covering.heap_fetches == 0
    assert covering.pages < heap_path.pages


def test_step5_the_index_change_is_expand_then_contract(connection, indexes):
    def names():
        return {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'orders'")}

    assert names() == {"orders_pkey", "idx_orders_created_id"}
    indexes.reset_to(1)
    assert names() == {"orders_pkey", "idx_orders_created_id", "idx_orders_listing"}, "both exist: no gap"
    indexes.reset_to(2)
    assert names() == {"orders_pkey", "idx_orders_listing"}


def test_migrations_run_twice_and_revert_in_reverse_order_without_harm(connection, indexes):
    from busy_listing.infrastructure.sql_script import run_file

    for path in indexes.migrations():
        run_file(connection, path)
        run_file(connection, path)
    for path in reversed(indexes.down_migrations()):
        run_file(connection, path)
        run_file(connection, path)
    names = {row[0] for row in connection.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'orders'")}
    assert names == {"orders_pkey", "idx_orders_created_id"}, "the downs restore the state before the migrations"


def test_step6_the_same_load_costs_far_less_database_time_after_the_fixes(orders, statistics, indexes):
    totals = {}
    for strategy, step in (("naive", 0), ("keyset", 2)):
        indexes.reset_to(step)
        statistics.reset()
        for index in range(60):
            page = PAGES[index % len(PAGES)]
            if strategy == "naive":
                orders.naive_page(page)
            else:
                orders.keyset_page(None)
        totals[strategy] = total_time_ms(statistics.snapshot())
    assert totals["naive"] > 20 * totals["keyset"], "the lesson saw about 42 times less database time"


def test_the_seed_script_leaves_tables_that_have_rows_alone():
    seed = (SQL / "002_seed.sql").read_text()
    assert "\\if :orders_empty" in seed
    assert "\\if :customers_empty" in seed


def test_the_bookmark_lookup_returns_a_cursor_per_deep_page(settings):
    driver = HttpLoadDriver("http://unused", settings.postgres)
    from busy_listing.domain.listing import Strategy

    bookmarks = driver.prepare(Strategy.KEYSET)
    assert set(bookmarks) == set(PAGES)
    assert bookmarks[0] is None
    created_at, _order_id = (Cursor.decode(str(bookmarks[10000])).created_at, 0)
    assert created_at < datetime(2027, 1, 1, tzinfo=UTC)
    assert driver.prepare(Strategy.NAIVE) == {}

"""One test per "Done when" line of the lesson. They run against the compose database after `make db`."""
import random
import threading
import time

import requests

from app import cursor, listing, stats
from app.db import SessionFactory
from scripts import lab, load

OFFSET_PAGE_10000 = ("SELECT * FROM orders ORDER BY created_at DESC, id DESC LIMIT 20 OFFSET {offset}")
KEYSET_PAGE = ("SELECT id, customer_id, status, total, created_at FROM orders "
               "WHERE (created_at, id) < (%s, %s) ORDER BY created_at DESC, id DESC LIMIT 20")


def get_orders(base_url, **params):
    response = requests.get(f"{base_url}/orders", params=params, timeout=60)
    response.raise_for_status()
    return response.json()


def run_naive_requests(base_url, count, strategy="naive"):
    chooser = random.Random(7)
    for _ in range(count):
        get_orders(base_url, strategy=strategy, page=chooser.choice(load.PAGES))


def pages_touched(plan):
    return plan["Plan"]["Shared Hit Blocks"] + plan["Plan"]["Shared Read Blocks"]


def test_step1_top_by_total_time_and_top_by_calls_are_different_queries(base_url, at_step):
    at_step(0)
    stats.reset()
    run_naive_requests(base_url, 60)
    by_time, by_calls = stats.top("total_exec_time")[0], stats.top("calls")[0]
    assert "FROM orders" in by_time["query"] and "OFFSET" in by_time["query"]
    assert "FROM customers WHERE customers.id = $1" in " ".join(by_calls["query"].split())
    assert by_time["query"] != by_calls["query"]
    assert by_calls["calls"] >= 15 * by_time["calls"], "a cheap statement run once per order, per page"
    assert by_time["mean_exec_time"] > 100 * by_calls["mean_exec_time"]


def test_step2_n_plus_one_is_two_statements_or_fewer_after_the_fix(base_url, query_counter):
    get_orders(base_url, strategy="naive", page=5)
    naive_statements = query_counter.count
    assert naive_statements >= 15, "one orders query plus one customer query per order"
    for strategy_params in ({"strategy": "batched", "page": 5}, {"strategy": "keyset"}, {}):
        before = query_counter.count
        get_orders(base_url, **strategy_params)
        assert query_counter.count - before <= 2, f"{strategy_params} issued too many statements"


def test_step2_per_order_lookup_disappears_from_the_next_ranking(base_url):
    stats.reset()
    run_naive_requests(base_url, 20, strategy="batched")
    ranked = stats.top("calls")
    assert not any("customers.id = $1" in " ".join(entry["query"].split()) for entry in ranked)
    lookup = next(entry for entry in ranked if "= ANY" in entry["query"])
    assert lookup["calls"] == 20, "one customer query per page load"


def test_step3_offset_reads_and_discards_every_row_before_the_page(connection, at_step):
    at_step(0)
    plans = {offset: lab.explain_json(connection, OFFSET_PAGE_10000.format(offset=offset))
             for offset in (0, 1980, 199980)}
    deep = plans[199980]
    assert deep["Plan"]["Node Type"] == "Limit" and deep["Plan"]["Actual Rows"] == 20
    produced = deep["Plan"]["Plans"][0]["Actual Rows"]
    assert produced == 199_980 + 20, "the scan below the Limit produced 200,000 rows to keep 20"
    assert pages_touched(plans[0]) < pages_touched(plans[1980]) < pages_touched(deep)
    assert deep["Execution Time"] > 20 * plans[0]["Execution Time"]


def test_step4_deep_keyset_page_costs_about_what_page_one_costs(connection, at_step):
    at_step(0)
    deep_bookmark = cursor.decode(load.bookmark(connection, 10000))
    first = lab.explain_json(connection, "SELECT id, customer_id, status, total, created_at FROM orders "
                             "ORDER BY created_at DESC, id DESC LIMIT 20")
    deep = lab.explain_json(connection, KEYSET_PAGE % (f"'{deep_bookmark[0].isoformat()}'", deep_bookmark[1]))
    deep_offset = lab.explain_json(connection, OFFSET_PAGE_10000.format(offset=199980))
    assert abs(pages_touched(deep) - pages_touched(first)) <= 10
    assert pages_touched(deep_offset) > 1000 * pages_touched(deep)
    assert deep["Execution Time"] * 20 < deep_offset["Execution Time"]


def test_step4_cursor_is_opaque_and_ties_never_split_a_page_boundary(connection):
    expected = [row[0] for row in connection.execute(
        "SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 11")]
    walked, token = [], None
    with SessionFactory() as session:
        for _ in range(6):                      # pages of 2 cross the groups of three equal timestamps
            rows, token = listing.list_orders_keyset(session, token, page_size=2)
            walked += [row["id"] for row in rows]
    assert walked[:11] == expected and token is not None
    assert "created_at" not in token and cursor.decode(token)[1] == walked[-1]


def test_step4_every_order_exactly_once_while_new_orders_are_inserted(connection):
    highest_id = connection.execute("SELECT max(id) FROM orders").fetchone()[0]
    stop = threading.Event()

    def insert_orders():
        with lab.connect() as writer:
            while not stop.is_set():
                writer.execute("INSERT INTO orders (customer_id, status, total, created_at) VALUES "
                               "(1, 'paid', 1, '2027-01-01'), (2, 'paid', 1, '2026-03-01 00:00:00+00'), "
                               "(3, 'paid', 1, '2026-03-01 00:00:00+00')")
                time.sleep(0.002)

    writer_thread = threading.Thread(target=insert_orders)
    writer_thread.start()
    walked, token = [], None
    try:
        with SessionFactory() as session:
            while True:
                rows, token = listing.list_orders_keyset(session, token, page_size=1000)
                walked += [row["id"] for row in rows]
                if token is None:
                    break
    finally:
        stop.set()
        writer_thread.join()
    inserted = connection.execute("SELECT count(*) FROM orders WHERE id > %s", (highest_id,)).fetchone()[0]
    connection.execute("DELETE FROM orders WHERE id > %s", (highest_id,))
    assert inserted > 0, "the writer really ran during the walk"
    assert len(walked) == len(set(walked)), "no order appeared twice"
    assert set(range(1, highest_id + 1)) <= set(walked), "no existing order was skipped"


def test_offset_paging_repeats_rows_when_a_new_order_arrives_between_pages(connection):
    with SessionFactory() as session:
        first = [row["id"] for row in listing.list_orders_batched(session, 0)[0]]
    connection.execute("INSERT INTO orders (customer_id, status, total, created_at) VALUES (1, 'paid', 1, '2027-01-01')")
    try:
        with SessionFactory() as session:
            second = [row["id"] for row in listing.list_orders_batched(session, 1)[0]]
    finally:
        connection.execute("DELETE FROM orders WHERE created_at = '2027-01-01'")
    assert first[-1] in second, "the last row of page 1 is shown again as the first row of page 2"


def test_step5_covering_index_gives_an_index_only_scan_with_no_heap_visits(connection, at_step):
    bookmark = cursor.decode(load.bookmark(connection, 10000))
    query = KEYSET_PAGE % (f"'{bookmark[0].isoformat()}'", bookmark[1])
    at_step(0)
    heap_path = lab.explain_json(connection, query)
    at_step(2)
    covering = lab.explain_json(connection, query)
    assert "Index Only Scan" in lab.node_types(covering)
    only_scan = next(node for node in lab.plan_nodes(covering) if node["Node Type"] == "Index Only Scan")
    assert only_scan["Heap Fetches"] == 0 and only_scan["Index Name"] == "idx_orders_listing"
    assert pages_touched(covering) < pages_touched(heap_path)


def test_step5_the_index_change_is_expand_then_contract(connection, at_step):
    def index_names():
        return {row[0] for row in connection.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'orders'")}

    at_step(0)
    assert index_names() == {"orders_pkey", "idx_orders_created_id"}
    at_step(1)
    assert index_names() == {"orders_pkey", "idx_orders_created_id", "idx_orders_listing"}, "both exist: no gap"
    at_step(2)
    assert index_names() == {"orders_pkey", "idx_orders_listing"}


def test_step6_the_same_load_costs_far_less_database_time_after_the_fixes(base_url, at_step):
    totals = {}
    for strategy, step in (("naive", 0), ("keyset", 2)):
        at_step(step)
        bookmarks = load.bookmarks_for(strategy)
        stats.reset()
        load.run_load(base_url, strategy, 60, seed=3, bookmarks=bookmarks)
        totals[strategy] = stats.total_database_time_ms()
    assert totals["naive"] > 20 * totals["keyset"], "the lesson saw about 42 times less database time; a busy machine inflates the small number"


def test_the_listing_endpoint_pages_through_with_an_opaque_cursor(base_url):
    first = get_orders(base_url)
    assert first["strategy"] == "keyset" and len(first["orders"]) == 20
    assert all(row["customer_name"].startswith("Customer ") for row in first["orders"])
    second = get_orders(base_url, cursor=first["next_cursor"])
    assert not {row["id"] for row in first["orders"]} & {row["id"] for row in second["orders"]}
    assert requests.get(f"{base_url}/orders", params={"page": 3}).status_code == 400


def test_common_mistake_a_cursor_on_created_at_alone_skips_tied_orders(connection):
    """Three orders share each created_at, so a bookmark without the id loses the ties at a page boundary."""
    expected = [row[0] for row in connection.execute("SELECT id FROM orders ORDER BY created_at DESC, id DESC LIMIT 12")]
    walked, last_created_at = [], None
    for _ in range(6):
        where = "WHERE created_at < %s" if last_created_at else ""
        rows = connection.execute(
            f"SELECT id, created_at FROM orders {where} ORDER BY created_at DESC, id DESC LIMIT 2",
            (last_created_at,) if last_created_at else ()).fetchall()
        walked += [row[0] for row in rows]
        last_created_at = rows[-1][1]
    assert walked != expected[:len(walked)], "tied rows at the page boundaries were skipped"

import pytest

from busy_listing.domain.errors import PlanParseError
from busy_listing.domain.plan import pages_touched, parse_json_plan, parse_text_plan

SEQ_SCAN = [
    "Seq Scan on orders  (cost=0.00..78125.01 rows=5000 width=456) (actual time=1.1..384.2 rows=2748.00 loops=1)",
    "  Filter: (date(created_at) = '2026-03-14'::date)",
    "  Rows Removed by Filter: 997252",
    "  Buffers: shared hit=47646 read=15479 written=158",
    "Planning Time: 0.042 ms",
    "Execution Time: 384.711 ms",
]
INDEX_ONLY = [
    "Index Only Scan using idx_orders_listing on orders  (cost=0.42..50.02 rows=960 width=33) (actual rows=1010.00)",
    "  Heap Fetches: 0",
    "  Buffers: shared hit=506",
    "Serialization: time=0.896 ms  output=69kB  format=text",
    "Execution Time: 2.095 ms",
]
SORT_OVER_BITMAP = [
    "Sort  (cost=3710.69..3713.21 rows=1006 width=457) (actual time=2.4..2.5 rows=1010.00 loops=1)",
    "  Buffers: shared hit=1009",
    "  ->  Bitmap Heap Scan on orders  (cost=29.48..3722.78 rows=1024 width=457) (actual time=0.1..1.9 rows=1010)",
    "        ->  Bitmap Index Scan on idx_orders_customer_created  (cost=0.00..29.23 rows=1024 width=0)",
    "Execution Time: 3.293 ms",
]


def test_a_sequential_scan_is_read_with_its_time_pages_and_discarded_rows():
    plan = parse_text_plan(SEQ_SCAN)
    assert plan.execution_ms == 384.711
    assert plan.pages == 47646 + 15479
    assert plan.node_types == ("Seq Scan",)
    assert plan.rows_removed_by_filter == 997252
    assert plan.heap_fetches is None
    assert plan.has_node("Seq Scan")
    assert not plan.has_node("Sort")


def test_an_index_only_scan_reports_the_index_and_zero_heap_fetches():
    plan = parse_text_plan(INDEX_ONLY)
    assert plan.index_names == ("idx_orders_listing",)
    assert plan.heap_fetches == 0
    assert plan.uses_index("idx_orders_listing")
    assert not plan.uses_index("orders_pkey")


def test_nested_nodes_and_bitmap_index_names_are_found():
    plan = parse_text_plan(SORT_OVER_BITMAP)
    assert plan.node_types == ("Sort", "Bitmap Heap Scan", "Bitmap Index Scan")
    assert plan.index_names == ("idx_orders_customer_created",)


def test_pages_after_serialization_are_added_to_the_top_nodes_pages():
    lines = [
        "Seq Scan on t  (cost=0..1 rows=1)",
        "  Buffers: shared hit=207",
        "Serialization: time=30 ms",
        "  Buffers: shared hit=10625",
    ]
    assert pages_touched(lines) == 207 + 10625


def test_a_plan_without_analyze_is_refused():
    with pytest.raises(PlanParseError, match="Execution Time"):
        parse_text_plan(["Seq Scan on orders  (cost=0.00..1.00 rows=1 width=1)"])


def test_json_plans_give_the_same_summary():
    document = {
        "Execution Time": 4.0,
        "Plan": {
            "Node Type": "Limit",
            "Shared Hit Blocks": 10,
            "Shared Read Blocks": 3,
            "Plans": [
                {"Node Type": "Index Scan", "Index Name": "idx_orders_customer_created", "Rows Removed by Filter": 7}
            ],
        },
    }
    plan = parse_json_plan(document)
    assert (plan.execution_ms, plan.pages) == (4.0, 13)
    assert plan.node_types == ("Limit", "Index Scan")
    assert plan.index_names == ("idx_orders_customer_created",)
    assert plan.rows_removed_by_filter == 7


def test_json_heap_fetches_are_reported():
    document = {
        "Execution Time": 1.0,
        "Plan": {"Node Type": "Index Only Scan", "Shared Hit Blocks": 1, "Shared Read Blocks": 0, "Heap Fetches": 0},
    }
    assert parse_json_plan(document).heap_fetches == 0


def test_a_json_plan_with_the_wrong_shape_is_refused():
    with pytest.raises(PlanParseError, match="unexpected JSON plan shape"):
        parse_json_plan({"Plan": {}})

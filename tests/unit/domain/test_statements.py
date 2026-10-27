from busy_listing.domain.statements import RankBy, StatementStat, merge_by_text, rank, total_calls, total_time_ms

LOOKUP = "SELECT name FROM customers WHERE id = $1"
LISTING = "SELECT * FROM orders ORDER BY created_at DESC OFFSET $1"


def rows() -> list[StatementStat]:
    return [
        StatementStat(LOOKUP, 3000, 15.0),
        StatementStat(LOOKUP, 3000, 18.0),  # the same text under a second query id (int2 against int4)
        StatementStat(LISTING, 300, 5000.0),
    ]


def test_rows_with_the_same_text_are_added_together():
    merged = {row.query: row for row in merge_by_text(rows())}
    assert merged[LOOKUP] == StatementStat(LOOKUP, 6000, 33.0)
    assert len(merged) == 2


def test_the_two_rankings_find_different_statements():
    assert rank(rows(), RankBy.TOTAL_TIME)[0].query == LISTING
    assert rank(rows(), RankBy.CALLS)[0].query == LOOKUP


def test_the_ranking_is_cut_to_the_limit():
    assert len(rank(rows(), RankBy.CALLS, limit=1)) == 1


def test_mean_time_is_total_over_calls_and_zero_for_no_calls():
    assert StatementStat(LISTING, 300, 5000.0).mean_ms == 5000.0 / 300
    assert StatementStat(LISTING, 0, 0.0).mean_ms == 0.0


def test_a_statement_is_shown_on_one_line():
    assert StatementStat("SELECT 1\n  FROM t\n", 1, 1.0).short == "SELECT 1 FROM t"


def test_totals_cover_every_statement():
    assert total_time_ms(rows()) == 5033.0
    assert total_calls(rows()) == 6300

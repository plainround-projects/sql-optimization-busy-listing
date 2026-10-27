from busy_listing.application.replay import LessonResult, PhaseResult
from busy_listing.application.report import render_results
from busy_listing.domain.plan import PlanSummary
from busy_listing.domain.statements import StatementStat


def phase(label: str, database_ms: float) -> PhaseResult:
    stat = StatementStat("SELECT customers | pipe", 6000, 30.6)
    return PhaseResult(label, (stat,), (stat,), database_ms, 6300, 8.3, {0: 8.7, 100: 10.8, 5000: 49.0, 10000: 85.9})


def result() -> LessonResult:
    plans = {"e1_offset_page10000": PlanSummary(110.0, 200751, (), (), 0, None)}
    return LessonResult(300, tuple(phase(f"phase {n}", 5000.0 / n) for n in (1, 2, 3, 4)), plans)


def test_the_phase_table_shows_database_time_and_page_medians():
    text = render_results(result())
    assert "| phase 1 | 5000 | 6300 | 8.3 | 8.7 | 10.8 | 49.0 | 85.9 |" in text


def test_the_plan_table_lists_the_captured_plans():
    assert "| `e1_offset_page10000` | 110.000 | 200751 |" in render_results(result())


def test_rankings_are_shown_for_the_first_and_last_phase_and_two_rows_for_the_others():
    text = render_results(result())
    assert "## Top ten, phase phase 1" in text
    assert "## Top ten, phase phase 4" in text
    assert "## Top two, phase phase 2" in text


def test_a_pipe_in_a_statement_does_not_break_the_table():
    assert "SELECT customers / pipe" in render_results(result())


def test_the_host_load_note_is_printed_when_it_is_known():
    from dataclasses import replace

    from busy_listing.domain.host import HostLoad

    text = render_results(replace(result(), host_load=HostLoad(40.0, 12)))
    assert "Measured on a loaded machine (load average 40.0 on 12 CPUs)" in text
    assert "Measured" not in render_results(result())

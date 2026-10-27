import pytest

from busy_listing.application.replay import ReplayLesson
from busy_listing.domain import lesson
from busy_listing.domain.errors import LessonInterruptedError
from busy_listing.domain.listing import Strategy

from .fakes import FakeDriver, FakeIndexes, FakePlans, FakeServer, FakeStatistics, RecordingStore


def build(**options):
    statistics, indexes, plans, store, server = (
        FakeStatistics(),
        FakeIndexes(),
        FakePlans(),
        RecordingStore(),
        FakeServer(),
    )
    driver = FakeDriver(statistics)
    replay = ReplayLesson(
        serve=server, driver=driver, statistics=statistics, indexes=indexes, plans=plans, store=store, **options
    )
    return replay, driver, statistics, indexes, plans, store, server


def test_the_four_phases_run_in_the_lessons_order_with_the_same_number_of_requests():
    replay, driver, *_ = build(requests=40)
    replay.run()
    measured = [run for run in driver.runs if run[1] == 40]
    assert [strategy for strategy, _ in measured] == [
        Strategy.NAIVE,
        Strategy.BATCHED,
        Strategy.KEYSET,
        Strategy.KEYSET,
    ]


def test_the_caches_are_warmed_with_five_requests_before_the_statistics_are_reset():
    replay, driver, statistics, *_ = build(requests=40)
    replay.run()
    assert [run[1] for run in driver.runs] == [5, 40] * 4
    assert statistics.resets == 4


def test_the_service_is_up_for_the_whole_replay_and_stopped_afterwards():
    replay, *_, server = build()
    replay.run()
    assert server.events == ["up", "down"]


def test_the_service_is_stopped_even_when_the_replay_is_interrupted():
    replay, *_, server = build(should_stop=lambda: True)
    with pytest.raises(LessonInterruptedError):
        replay.run()
    assert server.events == ["up", "down"]


def test_the_index_state_changes_before_the_first_and_the_last_phase_only():
    replay, _driver, _statistics, indexes, *_ = build()
    replay.run()
    assert indexes.states == [0, 2]


def test_every_plan_of_the_lesson_is_captured_and_saved():
    replay, _driver, _statistics, _indexes, plans, store, _server = build()
    result = replay.run()
    expected = set(lesson.OFFSET_PLANS) | {name for phase in lesson.PHASES for name in phase.captures}
    assert set(plans.captured) == expected == set(store.plans) == set(result.plans)


def test_the_top_by_time_and_the_top_by_calls_differ_in_the_naive_phase():
    replay, *_ = build(requests=300)
    first = replay.run().phases[0]
    assert first.by_time[0].query != first.by_calls[0].query
    assert first.by_calls[0].calls == 6000


def test_the_database_time_falls_across_the_phases():
    replay, *_ = build()
    phases = replay.run().phases
    assert phases[0].database_ms > 100 * phases[-1].database_ms


def test_the_notes_are_saved_once_at_the_end():
    replay, *_, store, _server = build()
    replay.run()
    assert store.report is not None
    assert store.report.startswith("# Results of the last")


def test_progress_is_reported_for_each_phase_and_plan():
    messages: list[str] = []
    replay, *_ = build(progress=messages.append)
    replay.run()
    assert lesson.PHASES[0].label in messages
    assert any(message.startswith("plan e1_offset_page10000") for message in messages)

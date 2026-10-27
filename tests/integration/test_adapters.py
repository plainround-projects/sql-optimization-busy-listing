"""The adapters that are not the lesson itself: statistics, health, settings against the real database."""

import pytest

from busy_listing.application.health import ProbeFailedError
from busy_listing.infrastructure.health_probes import PostgresListingProbe

pytestmark = pytest.mark.integration


def test_the_statistics_are_empty_after_a_reset_and_count_the_next_statements(orders, statistics):
    statistics.reset()
    assert statistics.snapshot() == []
    orders.keyset_page(None)
    # The driver may add a lowercase `select` of its own (a session setting); the page itself is an uppercase SELECT.
    assert {row.query.split()[0].upper() for row in statistics.snapshot()} == {"SELECT"}
    assert any("orders.created_at" in row.query for row in statistics.snapshot())


def test_the_health_probe_reports_the_seeded_orders(settings):
    assert "1,000,000 orders" in PostgresListingProbe(settings.postgres).check()


def test_the_health_probe_fails_with_a_named_error_when_the_database_cannot_be_reached(settings):
    import dataclasses

    unreachable = dataclasses.replace(settings.postgres, port=1, connect_timeout_seconds=1)
    with pytest.raises(ProbeFailedError, match="cannot query PostgreSQL"):
        PostgresListingProbe(unreachable).check()

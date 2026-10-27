"""The lesson's scenario end to end: the HTTP service answering, and the whole replay (make up db first)."""

import os
import re
import subprocess
import sys

import pytest
import requests

from busy_listing.domain.cursor import Cursor
from busy_listing.infrastructure.settings import Settings
from busy_listing.interfaces.service import running_service

pytestmark = pytest.mark.e2e

# A shared machine can take longer than the 5 s default to accept a connection while the replay runs.
SLOW_MACHINE = {"PG_CONNECT_TIMEOUT_SECONDS": os.environ.get("PG_CONNECT_TIMEOUT_SECONDS", "30")}


def program(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", f"busy_listing.interfaces.{module}", *args],
        capture_output=True,
        text=True,
        env={**os.environ, **SLOW_MACHINE},
        timeout=1800,
        check=False,
    )


def test_the_service_pages_through_with_an_opaque_cursor_and_refuses_what_it_cannot_answer():
    settings = Settings.from_env()
    base = f"http://{settings.app.host}:{settings.app.port}"
    with running_service(settings):
        health = requests.get(f"{base}/health", timeout=10)
        assert health.status_code == 200
        first = requests.get(f"{base}/orders", timeout=60).json()
        assert first["strategy"] == "keyset"
        assert len(first["orders"]) == 20
        assert all(order["customer_name"].startswith("Customer ") for order in first["orders"])
        second = requests.get(f"{base}/orders", params={"cursor": str(first["next_cursor"])}, timeout=60).json()
        assert not {o["id"] for o in first["orders"]} & {o["id"] for o in second["orders"]}
        assert Cursor.decode(second["next_cursor"]).created_at <= Cursor.decode(first["next_cursor"]).created_at
        assert requests.get(f"{base}/orders", params={"page": 3}, timeout=10).status_code == 400
        assert requests.get(f"{base}/orders", params={"cursor": "garbage"}, timeout=10).status_code == 400
        batched = requests.get(f"{base}/orders", params={"strategy": "batched", "page": "2"}, timeout=60)
        assert batched.status_code == 200
        assert len(batched.json()["orders"]) == 20


def test_the_health_command_is_green_on_the_seeded_database():
    result = program("health_cli")
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"ok postgres: [\d,]+ orders, pg_stat_statements loaded", result.stdout), result.stdout


def test_the_replay_ranks_the_statements_four_times_and_writes_the_notes(tmp_path):
    result = program("run_cli", "--output-dir", str(tmp_path), "--requests", "60")
    assert result.returncode == 0, result.stderr
    notes = (tmp_path / "results.md").read_text()
    assert "## Top ten, phase 1 naive" in notes
    assert "## Top ten, phase 4 keyset + covering index" in notes
    assert "FROM customers WHERE customers.id = $1" in notes
    assert "Index Only Scan using idx_orders_listing" in (tmp_path / "e3_keyset_page10000_covering.txt").read_text()
    assert len(list(tmp_path.glob("*.txt"))) == 6

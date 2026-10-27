import pytest

from busy_listing.application.health import ProbeFailedError
from busy_listing.domain.listing import Strategy
from busy_listing.domain.load import LoadTimings
from busy_listing.interfaces import health_cli, load_cli, run_cli, serve_cli


def test_a_missing_password_is_a_configuration_error_with_exit_code_2_for_every_program(monkeypatch, capsys):
    monkeypatch.delenv("PGPASSWORD", raising=False)
    assert health_cli.main([]) == 2
    assert run_cli.main([]) == 2
    assert serve_cli.main([]) == 2
    assert load_cli.main([]) == 2
    assert "PGPASSWORD" in capsys.readouterr().err


def test_health_is_exit_1_when_the_probe_fails(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")

    class Failing:
        name = "postgres"

        def __init__(self, _settings) -> None:
            pass

        def check(self) -> str:
            raise ProbeFailedError("pg_stat_statements is not installed; run make db")

    monkeypatch.setattr(health_cli, "PostgresListingProbe", Failing)
    assert health_cli.main([]) == 1
    assert "FAIL postgres: pg_stat_statements" in capsys.readouterr().out


def test_health_is_exit_0_when_the_probe_passes(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")

    class Passing:
        name = "postgres"

        def __init__(self, _settings) -> None:
            pass

        def check(self) -> str:
            return "1,000,000 orders, pg_stat_statements loaded"

    monkeypatch.setattr(health_cli, "PostgresListingProbe", Passing)
    assert health_cli.main([]) == 0
    assert "ok postgres" in capsys.readouterr().out


def test_the_load_command_prints_the_median_of_each_page(monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", "x")
    calls: list[tuple[object, ...]] = []

    class Driver:
        def __init__(self, base_url, _postgres, *, timeout_seconds, seed) -> None:
            calls.append((base_url, timeout_seconds, seed))

        def prepare(self, strategy):
            return {}

        def run(self, strategy, requests, bookmarks):
            calls.append((strategy, requests))
            return LoadTimings(((0, 4.0), (100, 9.0)), 1.0)

    monkeypatch.setattr(load_cli, "HttpLoadDriver", Driver)
    assert load_cli.main(["--strategy", "batched", "--requests", "10", "--seed", "3"]) == 0
    assert calls == [("http://127.0.0.1:8142", 60, 3), (Strategy.BATCHED, 10)]
    out = capsys.readouterr().out
    assert "2 requests" in out
    assert "page    100: median      9.0 ms" in out


def test_the_serve_command_runs_the_app_on_the_configured_address(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "x")
    monkeypatch.setenv("APP_PORT", "9123")
    served: dict[str, object] = {}
    monkeypatch.setattr(serve_cli, "build_app", lambda _settings: "the-app")
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: served.update(app=app, **kwargs))
    assert serve_cli.main([]) == 0
    assert served["app"] == "the-app"
    assert (served["host"], served["port"]) == ("127.0.0.1", 9123)


@pytest.mark.parametrize("argument", ["--requests", "x"])
def test_a_bad_argument_is_rejected_by_the_parser(argument):
    with pytest.raises(SystemExit):
        run_cli.main([argument])

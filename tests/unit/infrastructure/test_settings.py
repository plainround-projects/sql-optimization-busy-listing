import pytest

from busy_listing.domain.listing import Strategy
from busy_listing.infrastructure.settings import ConfigurationError, Settings

MINIMAL = {"PGPASSWORD": "s3cret-value"}


def test_defaults_describe_the_local_compose_setup():
    settings = Settings.from_env(MINIMAL)
    postgres, app = settings.postgres, settings.app
    assert (postgres.host, postgres.port, postgres.database, postgres.user) == ("localhost", 55432, "lab", "lab")
    assert (app.host, app.port, app.default_strategy, app.load_requests) == ("127.0.0.1", 8142, Strategy.KEYSET, 300)
    assert (app.http_timeout_seconds, app.pool_size) == (60, 5)
    assert settings.log_level == "INFO"
    assert settings.sql_dir.name == "sql"


def test_the_database_password_has_no_default():
    with pytest.raises(ConfigurationError, match="PGPASSWORD"):
        Settings.from_env({})


def test_the_password_never_appears_in_a_printed_settings_object():
    assert "s3cret-value" not in repr(Settings.from_env(MINIMAL))


def test_every_variable_can_be_overridden():
    settings = Settings.from_env(
        {
            **MINIMAL,
            "PGHOST": "db",
            "PGPORT": "6543",
            "PGDATABASE": "x",
            "PGUSER": "u",
            "APP_HOST": "0.0.0.0",
            "APP_PORT": "9000",
            "LISTING_STRATEGY": "naive",
            "LOAD_REQUESTS": "50",
            "HTTP_TIMEOUT_SECONDS": "5",
            "DB_POOL_SIZE": "2",
            "LAB_SQL_DIR": "/somewhere/sql",
            "LOG_LEVEL": "debug",
        }
    )
    assert (settings.postgres.host, settings.postgres.port) == ("db", 6543)
    assert (settings.app.host, settings.app.port, settings.app.default_strategy) == ("0.0.0.0", 9000, Strategy.NAIVE)
    assert (settings.app.load_requests, settings.app.http_timeout_seconds, settings.app.pool_size) == (50, 5, 2)
    assert (settings.log_level, str(settings.sql_dir)) == ("DEBUG", "/somewhere/sql")


@pytest.mark.parametrize(
    "extra",
    [
        {"PGPORT": "0"},
        {"APP_PORT": "five"},
        {"PGHOST": "  "},
        {"PG_STATEMENT_TIMEOUT_MS": "-1"},
        {"LISTING_STRATEGY": "fast"},
        {"LOAD_REQUESTS": "0"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_an_unusable_value_is_rejected_with_the_variable_name(extra):
    with pytest.raises(ConfigurationError, match=next(iter(extra))):
        Settings.from_env({**MINIMAL, **extra})


def test_settings_read_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "from-the-process")
    assert Settings.from_env().postgres.password == "from-the-process"

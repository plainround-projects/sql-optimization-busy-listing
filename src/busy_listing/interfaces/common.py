"""Startup shared by the programs: settings or a clear exit code 2, and the composition root."""

from __future__ import annotations

import os
import sys

from fastapi import FastAPI

from ..application.health import check_health
from ..application.list_orders import ListOrders
from ..domain.host import HostLoad
from ..infrastructure.health_probes import PostgresListingProbe
from ..infrastructure.logging import configure_logging
from ..infrastructure.orm import create_lab_engine
from ..infrastructure.settings import ConfigurationError, Settings
from ..infrastructure.sqlalchemy_orders import SqlAlchemyOrders
from .http_app import create_app


def load_settings() -> Settings | None:
    """Read and validate the environment, configure logging, or print the problem and return None."""
    try:
        settings = Settings.from_env()
    except ConfigurationError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return None
    configure_logging(settings.log_level)
    return settings


def build_app(settings: Settings) -> FastAPI:
    """Wire the use case to its adapters: the one place that knows which implementations are in use."""
    engine = create_lab_engine(settings.postgres, settings.app.pool_size)
    probe = PostgresListingProbe(settings.postgres)
    return create_app(
        ListOrders(SqlAlchemyOrders(engine)),
        settings.app.default_strategy,
        lambda: check_health([probe]),
    )


def measure_host_load() -> HostLoad:
    """The 1-minute load average and CPU count right now, so results can say how busy the machine was."""
    return HostLoad(os.getloadavg()[0], os.cpu_count() or 1)

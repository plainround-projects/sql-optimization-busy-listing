"""Replay the lesson: the same load four times (naive, N+1 fixed, keyset, keyset + covering index), ranking each.

python -m busy_listing.interfaces.run_cli [--output-dir DIR] [--requests N]
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from pathlib import Path

from ..application.replay import ReplayLesson
from ..domain.errors import LabError, LessonInterruptedError
from ..infrastructure.artifacts import FileArtifactStore
from ..infrastructure.http_load import HttpLoadDriver
from ..infrastructure.lab_indexes import PostgresLabIndexes
from ..infrastructure.logging import fields
from ..infrastructure.pg_stat_statements import PgStatStatements
from ..infrastructure.shutdown import ShutdownSignal
from .common import load_settings, measure_host_load
from .service import running_service

logger = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the replay. Exit codes: 0 done, 1 lab error, 2 bad configuration, 130 interrupted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="where plans and results.md go (default: sql/explain)")
    parser.add_argument("--requests", type=int, default=0, help="requests per phase (default LOAD_REQUESTS)")
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    shutdown = ShutdownSignal()
    shutdown.install()
    indexes = PostgresLabIndexes(settings.postgres, settings.sql_dir)
    replay = ReplayLesson(
        serve=lambda: running_service(settings),
        driver=HttpLoadDriver(
            f"http://{settings.app.host}:{settings.app.port}",
            settings.postgres,
            timeout_seconds=settings.app.http_timeout_seconds,
        ),
        statistics=PgStatStatements(settings.postgres),
        indexes=indexes,
        plans=indexes,
        store=FileArtifactStore(arguments.output_dir or settings.sql_dir / "explain"),
        requests=arguments.requests or settings.app.load_requests,
        host_load=measure_host_load(),
        progress=lambda message: logger.info(message),
        should_stop=lambda: shutdown.requested,
    )
    try:
        result = replay.run()
    except LessonInterruptedError:
        logger.warning("interrupted; the index state may be between phases, rerun to start clean")
        return 130
    except LabError as error:
        logger.error("the lesson failed", extra=fields(error=error))
        return 1
    for phase in result.phases:
        print(f"{phase.label:55} database time {phase.database_ms:9.0f} ms, {phase.statements:6} statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

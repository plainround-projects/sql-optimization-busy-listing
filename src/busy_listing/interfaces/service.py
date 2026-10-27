"""Run the listing service in this process: for a replay (a thread that stops cleanly) or in the foreground."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import requests
import uvicorn

from ..infrastructure.settings import Settings
from .common import build_app

logger = logging.getLogger(__name__)
HEALTH_WAIT_SECONDS = 30


@contextmanager
def running_service(settings: Settings) -> Iterator[None]:
    """Serve the app on a background thread until the block ends; in-flight requests finish before it stops."""
    server = uvicorn.Server(
        uvicorn.Config(build_app(settings), host=settings.app.host, port=settings.app.port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, name="listing-service")
    thread.start()
    deadline = time.monotonic() + HEALTH_WAIT_SECONDS
    url = f"http://{settings.app.host}:{settings.app.port}/health"
    try:
        while True:
            try:
                if requests.get(url, timeout=2).ok:
                    break
            except requests.RequestException:
                pass
            if time.monotonic() > deadline or not thread.is_alive():
                raise RuntimeError(f"the listing service did not become healthy within {HEALTH_WAIT_SECONDS} s")
            time.sleep(0.2)
        logger.info("listing service is up")
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        logger.info("listing service stopped")

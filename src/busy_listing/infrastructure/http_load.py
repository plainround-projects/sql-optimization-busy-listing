"""Adapter: the lesson's load script over HTTP. Implements `LoadDriver`.

It clicks through pages the way real users (and bots) do, deep pages included. The same seed gives the same
sequence of pages, so runs before and after a fix are comparable. For keyset paging a page number has no meaning,
so each page is reached from a bookmark: the cursor of the row just before it, looked up once before the timed run
(as a deep link or a saved position would provide).
"""

from __future__ import annotations

import logging
import random
import time

import requests

from ..domain.cursor import Cursor
from ..domain.lesson import PAGES
from ..domain.listing import PAGE_SIZE, Strategy
from ..domain.load import Bookmarks, LoadTimings
from .logging import fields
from .postgres import session
from .retry import retry
from .settings import PostgresSettings

logger = logging.getLogger(__name__)


class HttpLoadDriver:
    """Sends the listing requests to a running service and times each one."""

    def __init__(self, base_url: str, postgres: PostgresSettings, *, timeout_seconds: int = 60, seed: int = 1) -> None:
        self._base_url = base_url
        self._postgres = postgres
        self._timeout = timeout_seconds
        self._seed = seed

    def prepare(self, strategy: Strategy) -> Bookmarks:
        """For keyset paging, the cursor of the row before each page; empty for the other strategies."""
        if strategy is not Strategy.KEYSET:
            return {}
        bookmarks: dict[int, str | None] = {}
        with session(self._postgres) as connection:
            for page in PAGES:
                if page == 0:
                    bookmarks[page] = None
                    continue
                row = connection.execute(
                    "SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1",
                    (page * PAGE_SIZE - 1,),
                ).fetchone()
                bookmarks[page] = Cursor(row[0], row[1]).encode() if row else None
        return bookmarks

    def run(self, strategy: Strategy, requests_count: int, bookmarks: Bookmarks) -> LoadTimings:
        """Send `requests_count` requests with the fixed page sequence; fail loudly on any HTTP error."""
        chooser = random.Random(self._seed)
        timings: list[tuple[int, float]] = []
        http = requests.Session()
        started = time.perf_counter()
        for _ in range(requests_count):
            page = chooser.choice(PAGES)
            params: dict[str, str | int] = {"strategy": strategy.value}
            if strategy is Strategy.KEYSET:
                if bookmarks.get(page):
                    params["cursor"] = str(bookmarks[page])
            else:
                params["page"] = page
            began = time.perf_counter()
            self._get(http, params)
            timings.append((page, (time.perf_counter() - began) * 1000))
        wall = time.perf_counter() - started
        logger.info(
            "load finished", extra=fields(strategy=strategy.value, requests=requests_count, seconds=round(wall, 1))
        )
        return LoadTimings(tuple(timings), wall)

    def _get(self, http: requests.Session, params: dict[str, str | int]) -> None:
        def attempt() -> None:
            response = http.get(f"{self._base_url}/orders", params=params, timeout=self._timeout)
            response.raise_for_status()

        retry(attempt, attempts=3, base_delay_seconds=0.2, retry_on=(requests.ConnectionError, requests.Timeout))

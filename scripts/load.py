"""The lesson's load script: click through listing pages the way real users (and bots) do, deep pages included.

The same seed gives the same sequence of pages, so runs before and after a fix are comparable.
For keyset paging a page number has no meaning, so each page is reached from a bookmark: the cursor of the
row just before it, looked up once before the timed run (as a deep link or a saved position would be).
"""
import argparse
import os
import random
import statistics
import time

import requests

from app import cursor
from scripts import lab

PAGES = [0, 1, 2, 50, 100, 5000, 10000]    # includes genuinely deep pages
PAGE_SIZE = 20


def bookmark(connection, page):
    """Cursor for the last row of the page before `page`; None for the first page."""
    if page == 0:
        return None
    row = connection.execute(
        "SELECT created_at, id FROM orders ORDER BY created_at DESC, id DESC OFFSET %s LIMIT 1",
        (page * PAGE_SIZE - 1,)).fetchone()
    return cursor.encode(*row)


def bookmarks_for(strategy):
    """Bookmarks for every page, looked up once so they stay out of the timed run and the statistics."""
    if strategy != "keyset":
        return {}
    with lab.connect() as connection:
        return {page: bookmark(connection, page) for page in PAGES}


def run_load(base_url, strategy, requests_count=300, seed=1, bookmarks=None):
    """Return [(page, elapsed_ms)] for `requests_count` listing requests."""
    bookmarks = bookmarks if bookmarks is not None else bookmarks_for(strategy)
    chooser = random.Random(seed)
    session, timings = requests.Session(), []
    for _ in range(requests_count):
        page = chooser.choice(PAGES)
        params = {"strategy": strategy}
        if strategy == "keyset":
            if bookmarks[page]:
                params["cursor"] = bookmarks[page]
        else:
            params["page"] = page
        started = time.perf_counter()
        response = session.get(f"{base_url}/orders", params=params, timeout=60)
        response.raise_for_status()
        timings.append((page, (time.perf_counter() - started) * 1000))
    return timings


def median_by_page(timings):
    return {page: statistics.median(ms for p, ms in timings if p == page) for page in PAGES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=["naive", "batched", "keyset"], default="naive")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--base-url", default=f"http://localhost:{os.environ.get('APP_PORT', '8142')}")
    arguments = parser.parse_args()
    timings = run_load(arguments.base_url, arguments.strategy, arguments.requests, arguments.seed)
    print(f"{len(timings)} requests, {sum(ms for _, ms in timings) / 1000:.1f} s in total")
    for page, median_ms in median_by_page(timings).items():
        print(f"  page {page:>6}: median {median_ms:8.1f} ms")


if __name__ == "__main__":
    main()

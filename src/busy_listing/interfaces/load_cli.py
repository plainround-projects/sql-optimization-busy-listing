"""The lesson's load script on its own, against a running service (make serve in another terminal).

python -m busy_listing.interfaces.load_cli --strategy naive --requests 300
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from ..domain.listing import Strategy
from ..infrastructure.http_load import HttpLoadDriver
from .common import load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Send the load and print the median request time of each page."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", choices=[s.value for s in Strategy], default=Strategy.NAIVE.value)
    parser.add_argument("--requests", type=int, default=0, help="requests to send (default LOAD_REQUESTS)")
    parser.add_argument("--seed", type=int, default=1)
    arguments = parser.parse_args(argv)
    settings = load_settings()
    if settings is None:
        return 2
    strategy = Strategy.parse(arguments.strategy)
    driver = HttpLoadDriver(
        f"http://{settings.app.host}:{settings.app.port}",
        settings.postgres,
        timeout_seconds=settings.app.http_timeout_seconds,
        seed=arguments.seed,
    )
    bookmarks = driver.prepare(strategy)
    timings = driver.run(strategy, arguments.requests or settings.app.load_requests, bookmarks)
    print(f"{len(timings.requests)} requests, {timings.wall_seconds:.1f} s in total")
    for page, median in timings.median_by_page().items():
        print(f"  page {page:>6}: median {median:8.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

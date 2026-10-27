"""Serve the listing on APP_HOST:APP_PORT in the foreground; SIGINT and SIGTERM stop it after in-flight requests.

python -m busy_listing.interfaces.serve_cli
"""

from __future__ import annotations

from collections.abc import Sequence

import uvicorn

from .common import build_app, load_settings


def main(_argv: Sequence[str] | None = None) -> int:
    """Run until stopped; returns 2 when the configuration is unusable."""
    settings = load_settings()
    if settings is None:
        return 2
    uvicorn.run(build_app(settings), host=settings.app.host, port=settings.app.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# uvicorn

## What it is

**uvicorn** is the program that actually listens on a network port and speaks HTTP. A web framework such as FastAPI only defines *what to do* for each request; uvicorn accepts the connections, reads the requests, calls the application, and writes the responses back. It talks to the application through a standard interface called **ASGI** (Asynchronous Server Gateway Interface), which is why any ASGI server can run any ASGI application.

## Why this repository uses it

FastAPI does not listen on a port by itself. uvicorn is the server that runs the listing application, in two situations: in the foreground (`make serve`) and inside the replay (`make run`), where the replay starts the service, sends the load and stops the service again.

## Where it appears

| File | Role |
|---|---|
| `src/busy_listing/interfaces/serve_cli.py` | `uvicorn.run(...)` in the foreground. |
| `src/busy_listing/interfaces/service.py` | `uvicorn.Server` on a background thread for the replay. |
| `Makefile` | `serve` runs `busy-listing-serve`. |
| `Dockerfile` | The default `CMD` is `busy-listing-serve`. |
| `tests/unit/interfaces/test_cli.py` | Replaces `uvicorn.run` to check the address. |

## How it works underneath

**Starting.** Two ways. On the command line: `uvicorn module:app --port 8000`. From Python: `uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")`, which blocks until the server stops. For more control, build `uvicorn.Config(app, ...)` and `uvicorn.Server(config)`, then call `server.run()`.

**Event loop.** uvicorn runs one **event loop** (a single thread that juggles many connections, switching whenever one waits for data). Application functions declared with plain `def` are handed to a pool of worker threads by the framework, so the loop is never blocked by them.

**Settings used here.** `host` is the address to listen on; the default `127.0.0.1` accepts only connections from the same computer, `0.0.0.0` accepts connections from anywhere. `port` is the number to listen on (default 8000). `log_level` is `"critical"`, `"error"`, `"warning"`, `"info"`, `"debug"` or `"trace"`.

**Graceful shutdown.** When uvicorn receives `SIGINT` (Ctrl-C) or `SIGTERM` in the main thread, it stops accepting new connections, lets the requests that are in progress finish and then exits. A program that runs the server in a background thread cannot rely on signals going to that thread, so it asks the server to stop by setting `server.should_exit = True` and then waits for the thread to end (`thread.join`).

**Logs.** uvicorn logs one line per request at `info` level (`INFO: 127.0.0.1:52000 - "GET /orders HTTP/1.1" 200 OK`) and start-up lines.

## Walkthrough of this repository's use

### In the foreground

`src/busy_listing/interfaces/serve_cli.py`, lines 1 to 25:

```python
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
```

`main` loads the settings (exit code 2 when they are unusable, as in the command-line note), builds the application with `build_app(settings)` and calls `uvicorn.run(app, host=settings.app.host, port=settings.app.port, log_level="info")`. The call blocks: the program is the server until it is stopped. Ctrl-C (SIGINT) or `docker stop` (SIGTERM) makes uvicorn finish the requests in progress and return; `main` then returns `0`. The docstring says so. `host` and `port` come from `APP_HOST` (default `127.0.0.1`) and `APP_PORT` (default 8142).

### On a thread, for the replay

`src/busy_listing/interfaces/service.py`, lines 1 to 46:

```python
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
```

`running_service(settings)` is a context manager (standard-library note) used as `with running_service(settings):` by the replay.

- `uvicorn.Config(build_app(settings), host=..., port=..., log_level="warning")` describes the server; `log_level="warning"` keeps the per-request lines out of the replay's output. `uvicorn.Server(config)` creates it.
- `thread = threading.Thread(target=server.run, name="listing-service")` and `thread.start()` run `server.run` in a second thread. The main thread meanwhile waits until the service is healthy (HTTP note) and then `yield`s: the replay's body runs, sending the load.
- `finally:` runs when the body ends, also on an error or an interrupt: `server.should_exit = True` asks uvicorn to stop, `thread.join(timeout=15)` waits up to 15 seconds for the thread to end (uvicorn finishes requests in progress first), and a log line records it.
- The 30-second wait for health (`HEALTH_WAIT_SECONDS`) turns "the service never started" (for example because the port is taken) into a clear error: `RuntimeError("the listing service did not become healthy within 30 s")`.

## Try it yourself

1. `make up db` then `make serve`; the terminal shows uvicorn's start-up lines: `INFO:     Started server process [...]`, `INFO:     Waiting for application startup.`, `INFO:     Application startup complete.` and `INFO:     Uvicorn running on http://127.0.0.1:8142 (Press CTRL+C to quit)`. Press Ctrl-C: it prints `INFO:     Shutting down`, `Waiting for application shutdown.`, `Application shutdown complete.` and `Finished server process [...]`, and the command ends with exit code 0 (`echo $?`).
2. While it runs, `curl -s http://127.0.0.1:8142/health` prints the health JSON, and each request adds a line such as `INFO:     127.0.0.1:50305 - "GET /health HTTP/1.1" 200 OK` to the server terminal.
3. `APP_PORT=9000 make serve` listens on port 9000 instead.
4. Start `make serve` twice: the second one fails with an error that says it could not bind to the address because it is already in use.
5. `.venv/bin/python -c "import uvicorn; print(uvicorn.__version__)"` prints `0.54.0`.

## Mistakes people make

- Listening on `0.0.0.0` on a laptop and exposing a development service to the network.
- Listening on `127.0.0.1` inside a container and wondering why the published port does not answer.
- Running a blocking call in the event loop.
- Killing the server with SIGKILL, which skips the graceful shutdown.
- Using `reload=True` in production.

**How this repository avoids them.** Default host is the loopback address; only the Docker image sets `0.0.0.0`. The replay stops its server through `should_exit` and a bounded `join`. The service must answer `/health` before any load is sent. Signals stop the foreground server gracefully.

## Check yourself

1. What is the difference between FastAPI and uvicorn? *FastAPI defines the application's behaviour; uvicorn listens on the port and calls it.*
2. What does the default host `127.0.0.1` mean for who can connect? *Only programs on the same computer.*
3. What does graceful shutdown do with a request in progress? *It lets it finish before the server exits.*
4. How can a program stop a server it runs on a thread? *Set `server.should_exit = True` and join the thread.*
5. What is ASGI? *The standard interface between asynchronous Python web servers and applications.*

## Further reading

- uvicorn documentation (0.54): https://uvicorn.dev/ — "Settings", "Deployment" (running programmatically), "Server Behavior" (graceful shutdown).
- ASGI specification: https://asgi.readthedocs.io/en/latest/

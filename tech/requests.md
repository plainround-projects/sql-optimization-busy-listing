# requests

## What it is

**requests** is the most widely used Python library for sending HTTP requests (see the HTTP note). Instead of opening network connections and writing request text yourself, you call `requests.get(url)` and receive a `Response` object with the status code and the body.

## Why this repository uses it

The load script has to behave like a client of the web service: send real HTTP requests and time them. `requests` is the client library. It is also used once more to ask the service whether it is healthy before the load starts, and by the end-to-end test to talk to the running service.

## Where it appears

| File | Use |
|---|---|
| `src/busy_listing/infrastructure/http_load.py` | The load driver: one `requests.Session`, `get` with a timeout, `raise_for_status`, retries. |
| `src/busy_listing/interfaces/service.py` | `requests.get(url, timeout=2)` to wait for `/health`. |
| `tests/e2e/test_replay_and_service.py` | Calls the live service. |
| `pyproject.toml` | `requests>=2.32` (run time), `types-requests>=2.32` (type information). |
| `domain/`, `application/` | Never import requests (import-linter forbids it). |

## How it works underneath

**A call.** `requests.get(url, params={...}, timeout=60)` builds the URL (the `params` dictionary becomes the query string, percent-encoded), opens a TCP connection, sends the request, waits for the answer and returns a `Response`. `response.status_code` is the number; `response.ok` is true for any code below 400; `response.json()` decodes a JSON body; `response.text` is the body as text; `response.raise_for_status()` raises `requests.HTTPError` for a 4xx or 5xx code.

**Sessions.** `s = requests.Session()` remembers connections between calls and reuses them (**keep-alive**), which saves the cost of opening a new connection for each request. Calls are made on the session: `s.get(...)`.

**Timeout.** Without `timeout=`, requests waits forever. A number means seconds to wait for the connection and for each piece of the answer; exceeding it raises `requests.Timeout`.

**Exceptions** all derive from `requests.RequestException`: `requests.ConnectionError` (could not connect), `requests.Timeout`, `requests.HTTPError` (from `raise_for_status`).

**Type information.** The library itself has no type hints; the separate package `types-requests` provides them for mypy.

## Walkthrough of this repository's use

`src/busy_listing/infrastructure/http_load.py`, lines 29 to 37:

```python
class HttpLoadDriver:
    """Sends the listing requests to a running service and times each one."""

    def __init__(self, base_url: str, postgres: PostgresSettings, *, timeout_seconds: int = 60, seed: int = 1) -> None:
        self._base_url = base_url
        self._postgres = postgres
        self._timeout = timeout_seconds
        self._seed = seed

```

`HttpLoadDriver` is the adapter for the `LoadDriver` port (typing note). Its constructor stores the base URL (for example `http://127.0.0.1:8142`), the PostgreSQL settings (used only to look up bookmarks), the timeout (60 s) and the random seed.

`src/busy_listing/infrastructure/http_load.py`, lines 55 to 83:

```python
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
```

- `chooser = random.Random(self._seed)`: a random generator with a fixed seed, so every run chooses the same sequence of pages (`chooser.choice(PAGES)`), which makes the four phases comparable.
- `http = requests.Session()`: one session for the whole run, so connections are reused.
- `started = time.perf_counter()` / `began = time.perf_counter()`: a precise clock for durations; the time of each request in milliseconds is `(time.perf_counter() - began) * 1000`.
- `params: dict[str, str | int] = {"strategy": strategy.value}` builds the query parameters; for keyset a `cursor` is added if the page has a bookmark; for offset strategies `page` is added.
- `self._get(http, params)` sends one request. `_get` defines an inner function `attempt()` that does `http.get(f"{self._base_url}/orders", params=params, timeout=self._timeout)` and `response.raise_for_status()`, and passes it to `retry(...)` with `retry_on=(requests.ConnectionError, requests.Timeout)`: a refused connection or a timeout is tried again (up to 3 attempts, 0.2 s base delay with backoff and jitter); an HTTP error status is not retried and propagates as `requests.HTTPError`.
- After the loop the summary is logged with `fields(strategy=..., requests=..., seconds=...)` and returned as `LoadTimings(tuple(timings), wall)`.

`src/busy_listing/interfaces/service.py`, lines 29 to 40:

```python
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
```

Waiting for the service: `requests.get(url, timeout=2).ok` is true for a status below 400. A `requests.RequestException` (the service is not listening yet) is swallowed with `except requests.RequestException: pass`, the loop sleeps 0.2 s and tries again until the 30-second deadline.

## Try it yourself

1. `.venv/bin/python -c "import requests; print(requests.__version__)"` prints `2.34.2`.
2. With the real stack running (`make up db`, `make serve`): `.venv/bin/python -c "import requests; r = requests.get('http://127.0.0.1:8142/orders', params={'strategy': 'batched', 'page': 2}, timeout=10); print(r.status_code, r.url, len(r.json()['orders']))"` prints `200 http://127.0.0.1:8142/orders?strategy=batched&page=2 20`.
3. `.venv/bin/python -c "import requests; r = requests.get('http://127.0.0.1:8142/orders', params={'cursor': 'x'}, timeout=10); print(r.status_code, r.json()); r.raise_for_status()"` prints `400 {'error': 'the cursor is not one this service issued'}` and then ends with a `requests.exceptions.HTTPError: 400 Client Error`.
4. `make load STRATEGY=keyset` prints `300 requests, N s in total` and a median per page.
5. Stop the service and repeat command 2: it raises `requests.exceptions.ConnectionError`; this is what the retry in the load driver catches.

## Mistakes people make

- Forgetting `timeout=`.
- Not checking the status code, and using an error page as if it were data.
- Creating a new connection for every call in a loop, instead of using a `Session`.
- Retrying requests that are not safe to repeat.
- Building the URL with string concatenation (use `params`).

**How this repository avoids them.** Every call has a timeout; one `Session` per run; status errors raise; only connection errors and timeouts are retried, and only for `GET`; the library is confined to the infrastructure and interface layers.

## Check yourself

1. What does `params={"page": 3}` do? *Adds `?page=3` to the URL, correctly encoded.*
2. What does `raise_for_status()` do? *Raises `HTTPError` when the status code is 400 or higher.*
3. Why use a `Session`? *It reuses connections between requests.*
4. What happens without `timeout`? *The call can wait forever.*
5. What are `ConnectionError` and `Timeout`? *Exceptions for "could not connect" and "took too long"; both derive from `RequestException`.*

## Further reading

- requests 2.34 documentation: https://requests.readthedocs.io/en/latest/ — "Quickstart", "Advanced Usage" (sessions), "Timeouts".

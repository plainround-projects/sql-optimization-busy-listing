# HTTP

## What it is

**HTTP** (HyperText Transfer Protocol) is the set of rules by which a program on one computer asks a program on another computer for something and gets an answer. Web browsers use it, and so do programs talking to each other. A program that waits for requests and answers them is a **server** (or **service**); a program that sends requests is a **client**.

## Why this repository uses it

The listing is a web service and the load script is its client. The lesson measures what a user's click costs, so the clicks have to be real HTTP requests: they go through the web framework, the ORM and the database, as they would in production. HTTP is also what the health check of the service speaks.

## Where it appears

| File | Role |
|---|---|
| `src/busy_listing/interfaces/http_app.py` | The server side: `GET /orders` and `GET /health`. |
| `src/busy_listing/infrastructure/http_load.py` | The client side: the load script sends requests with `requests`. |
| `src/busy_listing/interfaces/service.py` | Starts the service and polls `/health` until it answers 200. |
| `tests/unit/interfaces/test_http_app.py`, `tests/e2e/test_replay_and_service.py` | Check the status codes and bodies. |
| `Dockerfile` | `EXPOSE 8142`; `APP_HOST=0.0.0.0` so the published port reaches the service. |

## How it works underneath

**Connection.** The client opens a **TCP connection** (a reliable two-way stream of bytes) to the server's **address** (a host name or number such as `127.0.0.1`, which always means "this same computer") and **port** (a number, 0 to 65535, choosing the program on that computer; here 8142). The server must be **listening** on that port. `0.0.0.0` as a listening address means "all network addresses of this computer".

**Request.** Plain text: a first line `GET /orders?page=3 HTTP/1.1` (the **method**, the **path** with a **query string** after `?`, the version), then **header** lines (`Host: localhost:8142`), then an optional body. `GET` asks to read something and should change nothing. The query string holds `name=value` pairs joined with `&`; special characters are percent-encoded (`%20` is a space).

**Response.** A status line `HTTP/1.1 200 OK`, headers (`Content-Type: application/json`), and a body. The **status code** tells the outcome: `200` OK; `400` the request was wrong (the client should change it); `404` not found; `422` the request was well-formed but its values were rejected; `500` the server failed; `503` the server cannot answer now.

**JSON bodies.** APIs usually answer with JSON text (see the JSON note) and `Content-Type: application/json`.

**Timeouts.** A client that waits forever for a response can hang a whole program, so clients set a timeout. A server may also take long under load.

**Health endpoints.** A path such as `/health` that answers 200 when the service can do its job and 503 when it cannot; used by container platforms and scripts to decide whether the service is ready.

**Idempotent and safe.** Repeating a `GET` gives the same result and changes nothing, so a client may safely retry it after a connection error.

## Walkthrough of this repository's use

The contract of the service:

| Request | Meaning | Answer |
|---|---|---|
| `GET /orders` | The default version (`keyset`, set by `LISTING_STRATEGY`), first page | `200`, JSON with `strategy`, `orders` (20 of them) and `next_cursor` |
| `GET /orders?strategy=naive&page=3` | Offset paging, page number 3 (the pages count from 0) | `200`, JSON; `next_cursor` is `null` |
| `GET /orders?cursor=<token>` | Keyset paging: the rows after the one the token names | `200` |
| `GET /orders?page=3` (keyset) | Not allowed: keyset has no page numbers | `400`, `{"error": "..."}` |
| `GET /orders?strategy=fast` | Unknown version | `400` |
| `GET /orders?cursor=garbage` | A token the service did not issue | `400` |
| `GET /orders?page=x` | `page` is not an integer | `422`, FastAPI's description of the problem |
| `GET /health` | Is the database usable? | `200` or `503`, JSON with one entry per check |

Everything is a `GET`: reading changes nothing, so a client may repeat a request safely. That is why the load driver retries failed requests.

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

The client side (the `requests` note explains the library): `params` becomes the query string. `"strategy"` is always sent; for keyset the `cursor` token is added when the page has a bookmark, otherwise `page` is sent. `http.get(f"{self._base_url}/orders", params=params, timeout=self._timeout)` sends the request to, for example, `http://127.0.0.1:8142/orders`, with a timeout of 60 seconds by default. `response.raise_for_status()` turns a 4xx or 5xx answer into an exception, so the load fails loudly instead of timing a failure. `retry(attempt, attempts=3, base_delay_seconds=0.2, retry_on=(requests.ConnectionError, requests.Timeout))` repeats a request up to 3 times only for connection errors and timeouts.

`src/busy_listing/interfaces/service.py`, lines 18 to 46:

```python
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

How the replay knows the service is ready: after starting the server on a thread, it loops asking `GET /health` (`requests.get(url, timeout=2).ok` is true for any status below 400), swallows connection errors while the server is still starting (`except requests.RequestException: pass`), waits 0.2 s between tries (`time.sleep(0.2)`), and gives up after 30 seconds or when the thread has died.

Addresses and ports: the service listens on `APP_HOST:APP_PORT` (`127.0.0.1:8142` by default, so only this computer can reach it); inside the Docker image `APP_HOST=0.0.0.0`. The load script reads the same two settings to build `http://{host}:{port}`.

## Try it yourself

See the FastAPI note for a script that serves the app on fakes without a database; with it, `curl -i` shows each status line and header. With the real stack: `make up db`, `make serve` in one terminal, then in another:

1. `curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:8142/health"` prints `200`.
2. `curl -s -i "http://localhost:8142/orders?strategy=batched&page=2" | head -5` shows the status line and headers.
3. `curl -s "http://localhost:8142/orders" | python3 -m json.tool | head -20` prints the first order, indented.
4. Copy the `next_cursor` from that output and run `curl -s "http://localhost:8142/orders?cursor=<token>"`: the next 20 orders.
5. `make load STRATEGY=naive` sends 300 requests and prints the median time for each page.

## Mistakes people make

- Calling a service without a timeout.
- Using status 200 for errors, so clients cannot tell success from failure.
- Putting secrets in the URL (they end up in logs).
- Retrying requests that change data without making them idempotent.
- Listening on `0.0.0.0` when only local access is needed, or on `127.0.0.1` inside a container and wondering why the published port does not work.

**How this repository avoids them.** Every request has a timeout; only `GET`s are retried; errors have meaningful status codes; the service listens on the loopback address by default; the load driver fails on any 4xx/5xx instead of timing it.

## Check yourself

1. What are the parts of an HTTP request? *A request line (method, path with query, version), headers, and an optional body.*
2. What does status `400` mean? *The client sent a bad request and should change it before trying again.*
3. What does `127.0.0.1` mean? *This same computer (loopback).*
4. What is the query string in `/orders?page=3&strategy=naive`? *`page=3&strategy=naive`, name-value pairs after the `?`.*
5. Why set a timeout on a client? *Without one, a slow or stuck server can make the client wait forever.*

## Further reading

- MDN, "An overview of HTTP": https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Overview and the status code list: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Status
- RFC 9110, HTTP Semantics: https://www.rfc-editor.org/rfc/rfc9110

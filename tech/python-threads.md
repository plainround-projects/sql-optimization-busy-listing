# Python threads

## What it is

A **thread** is an independent line of execution inside one running program. A program normally does one thing at a time; with threads it can wait for one thing while doing another: send statements to a database over four connections at once, or watch a clock once a second while others work. All the threads of a program share its memory. The standard module `threading` creates and manages them.

## Why this repository uses it

Two places need two things to happen at once. The replay must send load to the web service *while the service is running in the same program*, so the service runs on a background thread. And one test inserts new orders on a second thread while the main thread pages through all the orders, to prove that keyset paging returns every order exactly once even while data arrives.

## Where it appears

| File | Threads |
|---|---|
| `src/busy_listing/interfaces/service.py` | `running_service` runs uvicorn on a thread named `listing-service`. |
| `tests/integration/test_lesson_outcomes.py` | The walk test runs a writer thread with a stop `Event`. |
| `tests/unit/application/fakes.py` | `FakeServer`, a context manager standing in for the service (no thread). |
| `src/busy_listing/infrastructure/shutdown.py` | A `threading.Event` as the shutdown flag (command-line note). |
| FastAPI (not our code) | Runs the plain `def` route functions in a pool of worker threads (FastAPI note). |

## How it works underneath

**Creating and running.** `t = threading.Thread(target=function, args=(1,), name="load-1", daemon=True)` prepares a thread; `t.start()` starts it, and then `function(1)` runs at the same time as the code that called `start()`. `t.join(timeout=5)` waits up to 5 seconds for it to finish. `t.is_alive()` tells whether it is still running. A **daemon** thread does not keep the program alive: when the main thread ends, daemon threads are stopped abruptly.

**Taking turns.** CPython (the standard Python) runs Python code in only one thread at a time, switching between them (the *global interpreter lock*). So threads do not make CPU-heavy Python faster. They are the right tool when threads mostly **wait** — for the network, for a database, for `time.sleep` — because a waiting thread lets the others run. This repository's threads spend nearly all their time waiting for PostgreSQL.

**Sharing data safely.** Two threads that change the same list or counter at the same moment can corrupt it or produce wrong results. Tools:

- `threading.Lock()`: only one thread at a time can hold it. `with lock:` takes it for the block and always releases it. The load keeps one lock around its shared lists.
- `threading.Event()`: a thread-safe flag. `.set()` raises it, `.clear()` lowers it, `.is_set()` reads it, and `.wait(seconds)` sleeps until the flag is set **or** the time has passed (returning whether it was set). It is the standard way to say "stop" to threads.
- Immutable values and appending to a list are used with care: single operations such as `list.append` or `dict.pop` are safe in CPython, but a sequence of operations is not.

**Timing and pacing.** `time.monotonic()` is a clock that never goes backwards, suited to measuring intervals and deadlines. `event.wait(timeout)` is better than `time.sleep` for a worker that must also react to "stop".

**Stopping threads cleanly.** Python cannot kill a thread. The pattern is: the owner sets an Event, each thread checks it between units of work and returns, and the owner calls `join`.

**`threading.Timer(seconds, function)`** runs a function once after a delay on its own thread; `.start()` starts it and `.cancel()` cancels it.

**`threading.get_ident()`** returns a number identifying the current thread.

## Walkthrough of this repository's use

### The service on a thread

`src/busy_listing/interfaces/service.py`, lines 21 to 46:

```python
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

- `thread = threading.Thread(target=server.run, name="listing-service")` prepares a thread whose job is to run `server.run()` (it blocks until the server is told to stop); `thread.start()` starts it, and from then on the server runs at the same time as the code below.
- The main thread polls `/health` (HTTP note) until the service answers, giving up after 30 seconds or if `thread.is_alive()` is false (the server died while starting, for example because the port is taken).
- `yield` hands control back to the replay, which sends its load. The service keeps running on its thread.
- `finally:` `server.should_exit = True` tells uvicorn to finish and stop, and `thread.join(timeout=15)` waits for the thread to end, so no service survives the replay. (uvicorn note.)

### The walk test

`tests/integration/test_lesson_outcomes.py`, lines 115 to 139:

```python
def test_step4_every_order_exactly_once_while_new_orders_are_inserted(orders, connection, settings):
    highest_id = connection.execute("SELECT max(id) FROM orders").fetchone()[0]
    stop = threading.Event()

    def insert_orders() -> None:
        with session(settings.postgres) as writer:
            while not stop.is_set():
                writer.execute(
                    "INSERT INTO orders (customer_id, status, total, created_at) VALUES "
                    "(1, 'paid', 1, '2027-01-01'), (2, 'paid', 1, '2026-03-01 00:00:00+00'), "
                    "(3, 'paid', 1, '2026-03-01 00:00:00+00')"
                )
                time.sleep(0.002)

    writer_thread = threading.Thread(target=insert_orders)
    writer_thread.start()
    walked, cursor = [], None
    try:
        while True:
            page = orders.keyset_page(cursor, page_size=1000)
            walked += [order.id for order in page.orders]
            cursor = page.next_cursor
            if cursor is None:
                break
    finally:
```

`stop = threading.Event()` is a thread-safe flag. `insert_orders` is a function defined inside the test; it opens its own connection and inserts three rows every 2 milliseconds until `stop.is_set()`. The writer thread is created (`threading.Thread(target=insert_orders)`) and started; the main thread walks all the pages. In the `finally` block, `stop.set()` tells the writer to finish, `writer_thread.join()` waits for it, and only then are the inserted rows counted and deleted, so the test cleans up after itself even when an assertion fails.

### Threads you do not see

FastAPI runs a route declared with plain `def` (like `orders` and `health_endpoint`) on a worker thread from a pool, so a slow database call does not block other requests. SQLAlchemy's connection pool hands each of those threads its own connection.

## Try it yourself

1. A thread and an Event, with no database:

   ```bash
   .venv/bin/python - <<'EOF'
   import threading, time
   stop = threading.Event()
   def worker():
       n = 0
       while not stop.wait(0.2):      # wakes every 0.2 s, or at once when stop is set
           n += 1
       print("worker saw", n, "ticks")
   t = threading.Thread(target=worker, name="demo")
   t.start()
   time.sleep(1.0)
   stop.set()
   t.join()
   print("alive after join:", t.is_alive())
   EOF
   ```

   It prints `worker saw 4 ticks` (occasionally 5; timing varies by a tick) and `alive after join: False`.
2. A lock protecting a shared counter:

   ```bash
   .venv/bin/python - <<'EOF'
   import threading
   n = 0
   lock = threading.Lock()
   def add():
       global n
       for _ in range(100_000):
           with lock:
               n += 1
   threads = [threading.Thread(target=add) for _ in range(4)]
   for t in threads: t.start()
   for t in threads: t.join()
   print(n)
   EOF
   ```

   It prints `400000`.
3. `make up db` then `make run` and watch the log: `listing service is up` appears before the first phase and `listing service stopped` after the last (the lines come from the thread's context manager).
4. While `make serve` runs, `curl -s http://127.0.0.1:8142/health` is answered by a worker thread of the server.

## Mistakes people make

- Expecting threads to speed up CPU-bound Python.
- Sharing a list or dict between threads without a lock, and reading half-updated data.
- Forgetting `join`, so the program ends while work is unfinished (or, for non-daemon threads, never ends).
- Using `time.sleep` in a worker that should stop promptly (use `Event.wait`).
- Letting an exception kill a thread silently; catch and record errors inside the thread function.
- Holding a lock while waiting for something slow.

**How this repository avoids them.** The service thread is always stopped and joined in a `finally`; the test's writer thread is stopped with an Event and joined before the data is counted; no data is shared between the threads except through the database; and the domain and application layers contain no threads.

## Check yourself

1. Why do threads help a program that talks to a database? *While one thread waits for the database, others can run.*
2. What does `Event.wait(1.0)` do? *Sleeps until the event is set or one second has passed, whichever comes first.*
3. What does `with lock:` guarantee? *Only one thread at a time runs the block, and the lock is released afterwards even on an error.*
4. How do you stop a thread? *Set an Event it checks between units of work, then `join` it; threads cannot be killed from outside.*
5. What is a daemon thread? *A thread that does not keep the program alive: it is stopped when the main thread ends.*

## Further reading

- `threading` module (3.13): https://docs.python.org/3.13/library/threading.html
- Thread-safe objects and the GIL: https://docs.python.org/3.13/glossary.html#term-global-interpreter-lock

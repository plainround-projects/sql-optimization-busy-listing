import socket
import threading
import time

import pytest
import requests
import uvicorn
from sqlalchemy import event

from app.db import engine
from app.main import app
from scripts import lab


@pytest.fixture(scope="session")
def connection():
    with lab.connect() as live_connection:
        yield live_connection


@pytest.fixture
def at_step(connection):
    """Return a function that sets the index state: 0 original ordering index, 1 both, 2 covering only."""
    return lambda step: lab.reset_to(connection, step)


@pytest.fixture(scope="session")
def base_url():
    """The real app on a free port, served by uvicorn in a thread of the test process."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            if requests.get(f"http://127.0.0.1:{port}/health", timeout=1).ok:
                break
        except requests.ConnectionError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


class StatementCounter:
    def __init__(self):
        self.statements = []

    @property
    def count(self):
        return len(self.statements)


@pytest.fixture
def query_counter():
    """Counts every statement the app's engine sends to PostgreSQL while the test runs."""
    counter = StatementCounter()

    def record(connection, cursor, statement, parameters, context, executemany):
        counter.statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield counter
    event.remove(engine, "before_cursor_execute", record)

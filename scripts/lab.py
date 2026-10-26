"""Small helpers shared by run_lesson.py and the tests: connect, run SQL files, read plans, set the index state."""
import os
import re
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
EXPLAIN_DIR = SQL_DIR / "explain"
MIGRATIONS = sorted((SQL_DIR / "migrations").glob("*.sql"))
LESSON_INDEXES = ["idx_orders_created_id", "idx_orders_listing"]


def connect(autocommit=True):
    """Connection from the PG* variables (the same ones psql and the Makefile use).

    Parallel query is switched off for the session so plans read the same on the compose database
    and on a CI service container, whose server defaults differ.
    """
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "55432"),
        user=os.environ.get("PGUSER", "lab"),
        password=os.environ.get("PGPASSWORD", "lab"),
        dbname=os.environ.get("PGDATABASE", "lab"),
        options="-c max_parallel_workers_per_gather=0",
        autocommit=autocommit,
    )


def split_statements(sql_text):
    """Split a SQL file on semicolons, ignoring comments and quoted text."""
    without_comments = re.sub(r"--[^\n]*", "", sql_text)
    statements, current, quote = [], [], None
    for character in without_comments:
        if quote:
            quote = None if character == quote else quote
        elif character in ("'", '"'):
            quote = character
        elif character == ";":
            statements.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    return [statement for statement in statements if statement]


def run_file(connection, path):
    """Run every statement of a file on one connection; return the rows of the last one that returns rows."""
    rows = []
    for statement in split_statements(Path(path).read_text()):
        cursor = connection.execute(statement)
        if cursor.description:
            rows = cursor.fetchall()
    return rows


def plan_lines(connection, path):
    """Run an explain/*.sql file and return the plan as text lines."""
    return [row[0] for row in run_file(connection, path)]


def execution_ms(lines):
    return float(re.search(r"Execution Time: ([\d.]+) ms", "\n".join(lines)).group(1))


def buffers_touched(lines):
    """Pages a plan touched: the top node's 'Buffers: shared hit=.. read=..' plus the pages read to send
    the rows to the client (the line after 'Serialization:'), where out-of-line TOAST values are fetched."""
    total, after_serialization = 0, False
    for line in lines:
        match = re.search(r"Buffers: shared (.*)", line)
        if line.startswith("Serialization:"):
            after_serialization = True
        elif match and (after_serialization or total == 0):
            total += sum(int(count) for count in re.findall(r"(?:hit|read)=(\d+)", match.group(1)))
            after_serialization = False
    return total


def explain_json(connection, query):
    """Plan of a query as the JSON tree PostgreSQL returns, with real timings and buffers."""
    cursor = connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query)
    return cursor.fetchone()[0][0]


def plan_nodes(plan):
    """Every node of a JSON plan, parent first."""
    node = plan.get("Plan", plan)
    yield node
    for child in node.get("Plans", []):
        yield from plan_nodes(child)


def node_types(plan):
    return [node["Node Type"] for node in plan_nodes(plan)]


def reset_to(connection, step):
    """Index state after migration number `step`: 0 is the original ordering index, 2 is the covering index only."""
    for index in LESSON_INDEXES:
        connection.execute(f"DROP INDEX IF EXISTS {index}")
    connection.execute("CREATE INDEX idx_orders_created_id ON orders (created_at DESC, id DESC)")
    for migration in MIGRATIONS[:step]:
        run_file(connection, migration)
    connection.execute("VACUUM ANALYZE orders")

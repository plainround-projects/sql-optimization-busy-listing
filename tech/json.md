# JSON

## What it is

**JSON** (JavaScript Object Notation) is a text format for structured data that almost every language and tool can read and write. It is the usual format for data sent between programs.

## Why this repository uses it

JSON is the language the pieces speak to each other in: the listing service answers requests with JSON, the cursor token is base64 of a small JSON document, the tests read PostgreSQL's plans as JSON, and the logging module uses JSON quoting for values with spaces.

## Where it appears

| File | Use |
|---|---|
| `src/busy_listing/interfaces/http_app.py` | The bodies of `GET /orders`, `GET /health` and the error answers. |
| `src/busy_listing/domain/cursor.py` | The payload `{"t": ..., "i": ...}` inside the cursor token. |
| `src/busy_listing/domain/plan.py` | `parse_json_plan` reads the JSON form of a plan. |
| `tests/integration/conftest.py` | `explain` asks PostgreSQL for `FORMAT JSON`. |
| `src/busy_listing/infrastructure/logging.py` | `json.dumps(text)` quotes log values. |
| `tests/unit/interfaces/test_http_app.py`, `tests/e2e/...` | Read the answers with `.json()`. |

## How it works underneath

A JSON text holds one **value**, which is one of:

- an **object**: `{"name": "orders", "pages": 12}`: curly braces around `"key": value` pairs separated by commas; keys are always double-quoted text;
- an **array**: `[1, 2, 3]`: square brackets around values separated by commas;
- a **string**: `"text"` in double quotes, with `\"` and `\n` escapes;
- a **number**: `12`, `-3.5`, `1e6`;
- `true`, `false`, `null`.

There are no comments and no trailing commas. In Python, the standard module `json` converts: `json.loads(text)` turns JSON text into Python values (objects become `dict`, arrays `list`, strings `str`, numbers `int` or `float`, `null` becomes `None`) and `json.dumps(value)` does the reverse. `json.dumps("two words")` gives `"two words"` including the quotes, which is also a handy way to quote a string.

**JSON Lines (`.jsonl`)** puts one complete JSON object on each line of a file, which suits logs and measurements that are appended over time.

PostgreSQL can return query results as JSON: `EXPLAIN (FORMAT JSON)` returns the plan as a JSON document, and the `psycopg` driver decodes a `json` column into Python lists and dictionaries by itself.

## Walkthrough of this repository's use

### The service's answers

`src/busy_listing/interfaces/http_app.py`, lines 18 to 33:

```python
def _body(strategy: Strategy, page: Page) -> dict[str, Any]:
    return {
        "strategy": strategy.value,
        "orders": [
            {
                "id": order.id,
                "customer_id": order.customer_id,
                "customer_name": order.customer_name,
                "status": order.status,
                "total": order.total,
                "created_at": order.created_at.isoformat(),
            }
            for order in page.orders
        ],
        "next_cursor": page.next_cursor.encode() if page.next_cursor else None,
    }
```

The Python dictionary that `_body` returns becomes this JSON (FastAPI converts it): an **object** with `"strategy"` (a string), `"orders"` (an **array** of objects, each with `"id"` and `"customer_id"` as numbers and `"customer_name"`, `"status"`, `"total"`, `"created_at"` as strings) and `"next_cursor"` (a string or `null`). `None` in Python is `null` in JSON. Money is a string, `"10.00"`, because JSON numbers are floating point and would round; a timestamp is an ISO-8601 string because JSON has no date type.

A real answer (from the unit-test fake) looks like:

```json
{"strategy":"keyset","orders":[{"id":3,"customer_id":1,"customer_name":"Customer 1","status":"paid","total":"10.00","created_at":"2026-05-04T11:02:00+00:00"}],"next_cursor":"eyJ0IjoiMjAyNi0wNS0wNFQxMTowMjowMCswMDowMCIsImkiOjN9"}
```

Errors are JSON too: `{"error": "the cursor is not one this service issued"}` with status 400, and FastAPI's own 422 answer is `{"detail": [{"type": "int_parsing", "loc": ["query", "page"], "msg": "...", "input": "x"}]}`.

### The cursor's payload

`src/busy_listing/domain/cursor.py`, lines 25 to 38:

```python
    def encode(self) -> str:
        """The opaque token handed to the client."""
        payload = json.dumps({"t": self.created_at.isoformat(), "i": self.order_id}, separators=(",", ":"))
        return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        """Read a token back; raises `InvalidCursorError` for anything this service did not issue."""
        try:
            padded = token + "=" * (-len(token) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            return cls(datetime.fromisoformat(payload["t"]), int(payload["i"]))
        except (binascii.Error, ValueError, KeyError, TypeError) as error:
            raise InvalidCursorError("the cursor is not one this service issued") from error
```

`json.dumps({"t": self.created_at.isoformat(), "i": self.order_id}, separators=(",", ":"))` produces the compact text `{"t":"2026-05-04T11:02:00+00:00","i":832765}` (`separators` removes the spaces). That text is base64-encoded into the token. `json.loads(...)` reads it back; a payload that is not valid JSON raises `ValueError` (specifically `json.JSONDecodeError`, a kind of `ValueError`), which `decode` turns into `InvalidCursorError`.

### JSON plans

`src/busy_listing/domain/plan.py`, lines 79 to 100:

```python
def _json_nodes(node: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield node
    for child in node.get("Plans", []):
        yield from _json_nodes(child)


def parse_json_plan(document: Mapping[str, Any]) -> PlanSummary:
    """Summarize one element of the JSON that `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` returns."""
    try:
        root = document["Plan"]
        nodes = list(_json_nodes(root))
        fetches = [node["Heap Fetches"] for node in nodes if "Heap Fetches" in node]
        return PlanSummary(
            execution_ms=float(document["Execution Time"]),
            pages=int(root["Shared Hit Blocks"]) + int(root["Shared Read Blocks"]),
            node_types=tuple(node["Node Type"] for node in nodes),
            index_names=tuple(dict.fromkeys(node["Index Name"] for node in nodes if "Index Name" in node)),
            rows_removed_by_filter=sum(int(node.get("Rows Removed by Filter", 0)) for node in nodes),
            heap_fetches=int(fetches[0]) if fetches else None,
        )
    except (KeyError, TypeError) as error:
        raise PlanParseError(f"unexpected JSON plan shape: missing {error}") from error
```

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) <query>` returns the plan as a JSON array with one document; psycopg decodes it into Python lists and dictionaries. `_json_nodes` walks the tree (a generator that calls itself on each child in `"Plans"`); `parse_json_plan` collects the facts with comprehensions and `node.get("Rows Removed by Filter", 0)` reads an optional key. Missing keys raise `KeyError`, which becomes a `PlanParseError`. The keys the code reads: `"Plan"`, `"Node Type"`, `"Plans"`, `"Index Name"`, `"Shared Hit Blocks"`, `"Shared Read Blocks"`, `"Rows Removed by Filter"`, `"Heap Fetches"` and the top-level `"Execution Time"`. The tests also read `"Actual Rows"`.

`src/busy_listing/infrastructure/logging.py`, lines 12 to 14:

```python
def _quote(value: object) -> str:
    text = str(value)
    return json.dumps(text) if not text or any(char in text for char in ' ="\n') else text
```

`json.dumps(text)` returns the text wrapped in double quotes with special characters escaped; used here only when a log value contains a space, an equals sign, a double quote or a line break.

## Try it yourself

1. `.venv/bin/python -c "import json; print(json.dumps('two words'), json.dumps('plain'))"` prints `"two words" "plain"`.
2. `.venv/bin/python -c "import json; d=json.loads('{\"Plan\": {\"Node Type\": \"Limit\"}}'); print(d['Plan']['Node Type'], d.get('Execution Time'))"` prints `Limit None`.
3. `.venv/bin/python -c "import json; print(json.dumps({'t': '2026-05-04T11:02:00+00:00', 'i': 7}, separators=(',', ':')))"` prints `{"t":"2026-05-04T11:02:00+00:00","i":7}`.
4. With the service running (`make serve`): `curl -s "http://localhost:8142/orders" | python3 -m json.tool | head -20` prints the first order with indentation.
5. `docker compose exec db psql -U lab -d lab -t -A -c "explain (analyze, buffers, format json) select count(*) from orders"` prints the JSON plan; look for `"Node Type"`, `"Plans"`, `"Shared Hit Blocks"`.

## Mistakes people make

- Single quotes or unquoted keys (not valid JSON).
- A trailing comma after the last item.
- Expecting dates: JSON has no date type, only text.
- Reading a JSON number as exact when it is a float.
- Indexing a missing key without a fallback (`d["x"]` raises `KeyError`; `d.get("x")` returns `None`).

**How this repository avoids them.** JSON is produced and read with `json` or the framework, never by string concatenation or regular expressions; money and times are strings; optional keys use `.get`; a wrong shape becomes a named error (`PlanParseError`, `InvalidCursorError`).

## Check yourself

1. What are the two container types in JSON? *Objects (key-value pairs in braces) and arrays (lists in brackets).*
2. How does Python represent a JSON object? *As a `dict`.*
3. What does `json.dumps("a b")` return? *The text `"a b"` including the double quotes.*
4. Is `{'a': 1}` valid JSON? *No; keys and strings need double quotes.*
5. What is JSON Lines? *A file with one JSON object per line.*

## Further reading

- ECMA-404 / json.org: https://www.json.org/json-en.html
- Python `json` module: https://docs.python.org/3.13/library/json.html

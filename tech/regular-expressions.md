# Regular expressions

## What it is

A **regular expression** (regex) is a short pattern that describes a family of texts, used to find or pull out pieces of text. `Execution Time: ([\d.]+) ms` describes "the words `Execution Time: `, then some digits and dots, then ` ms`", and can hand back the digits. Python has them in the standard library module `re`.

## Why this repository uses it

The lesson reads query plans: the text that `EXPLAIN (ANALYZE, BUFFERS)` prints. The numbers it needs (the time, the pages, the node types, which index) are in lines of fixed shape, so a handful of regular expressions pulls them out. The replay reads every plan it captures with them, and the "Plans for the deep page" table of `results.md` is built from the numbers they extract.

## Where it appears

| File | Patterns |
|---|---|
| `domain/plan.py` | `_EXECUTION`, `_BUFFERS`, `_PAGE_COUNTS`, `_NODE`, `_INDEX`, `_REMOVED`, `_HEAP_FETCHES` |
| `tests/e2e/test_replay_and_service.py` | One pattern checking the health command's output. |

## How it works underneath

**Matching.** The regex engine tries the pattern at each position of the text, left to right, and reports the first place where the whole pattern fits. `re.search(pattern, text)` returns a *match object* (or `None` if nothing fits). `pattern.findall(text)` returns every match.

**Building blocks.**

| Piece | Meaning |
|---|---|
| a plain character, e.g. `a` or `:` | itself |
| `.` | any one character except a line break |
| `\d` | one digit 0 to 9 |
| `\w` | one letter, digit or underscore |
| `\s` | one space, tab or line break |
| `[abc]` | one of the characters listed; `[a-z]` a range; `[\d.]` a digit or a dot (a dot inside brackets is just a dot); `[^x]` anything but x |
| `*` | the previous piece zero or more times |
| `+` | one or more times |
| `?` | zero or one time |
| `+?` and `*?` | the same, but as few as possible ("lazy") |
| `(...)` | a **group**: remembers the text it matched, available as `match.group(1)`; with `findall`, a pattern with one group returns the group's text |
| `(?:...)` | a group for structure only, remembers nothing |
| `a|b` | a or b |
| `^` and `$` | start and end of the text, or of each line with `re.MULTILINE` |
| `\` before a symbol | the symbol itself, e.g. `\(` is a bracket |

**Raw strings.** Write patterns as `r"..."`. In a raw string a backslash is kept as typed, so `r"\d"` is the two characters `\d` that the regex engine wants. Without `r`, Python would try to read `\d` itself.

**Compiling.** `re.compile(pattern)` prepares the pattern once so it can be reused; module-level constants named `_NAME` hold them.

**Flags.** `re.MULTILINE` makes `^` match at the start of every line.

**Limits.** A regex reads text, not structure. It is a good fit for reading the fixed shapes of lines printed by a program; it is a poor fit for nested formats like HTML.

## Walkthrough of this repository's use

The plan that the examples read (`sql/explain/e1_offset_page10000.txt`, page 10,000 by offset paging):

```text
Limit  (cost=14936.53..14938.02 rows=20 width=49) (actual time=188.438..188.463 rows=20.00 loops=1)
  Buffers: shared hit=200751
  ->  Index Scan using idx_orders_created_id on orders  (cost=0.42..74688.42 rows=1000000 width=49) (actual time=0.027..181.132 rows=200000.00 loops=1)
        Index Searches: 1
        Buffers: shared hit=200751
Planning Time: 0.224 ms
Execution Time: 188.513 ms
```

`src/busy_listing/domain/plan.py`, lines 16 to 22:

```python
_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")
_BUFFERS = re.compile(r"Buffers: shared (.*)")
_PAGE_COUNTS = re.compile(r"(?:hit|read)=(\d+)")
_NODE = re.compile(r"^\s*(?:->\s*)?([A-Z][A-Za-z ]+?)(?: using \w+| on \w+| \(cost)", re.MULTILINE)
_INDEX = re.compile(r"(?:using|Bitmap Index Scan on) (\w+)")
_REMOVED = re.compile(r"Rows Removed by Filter: (\d+)")
_HEAP_FETCHES = re.compile(r"Heap Fetches: (\d+)")
```

- `_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")` matches the last line. `Execution Time: ` is literal text. `([\d.]+)` is a group of one or more characters that are digits or dots; it captures `188.513`. ` ms` is literal. `search` finds the line anywhere in the text; `group(1)` is `188.513`.
- `_BUFFERS = re.compile(r"Buffers: shared (.*)")` matches `Buffers: shared hit=200751` (the first such line is the top node's) and captures everything after `shared ` to the end of the line (`.*`): `hit=200751`. (When pages also had to be read from outside the cache the line would read `hit=2058 read=61692`.)
- `_PAGE_COUNTS = re.compile(r"(?:hit|read)=(\d+)")` finds `hit=200751`, and in a line with both counters also `read=...`. `(?:hit|read)` means "hit or read" without remembering which; `=` is literal; `(\d+)` captures the digits. `findall` on `hit=2058 read=61692` returns `['2058', '61692']`; on the line above it returns `['200751']`. The function `pages_touched` adds the numbers: 200,751 pages for this plan.
- `_NODE = re.compile(r"^\s*(?:->\s*)?([A-Z][A-Za-z ]+?)(?: using \w+| on \w+| \(cost)", re.MULTILINE)` finds the name of each plan step. With `re.MULTILINE`, `^` matches at the start of every line. `\s*` skips leading spaces. `(?:->\s*)?` is an optional arrow: child steps in a plan start with `->`. `([A-Z][A-Za-z ]+?)` captures a capital letter followed by letters and spaces, as few as possible (`+?` is lazy). The last group `(?: using \w+| on \w+| \(cost)` says what must follow the name: ` using index_name`, ` on table_name` or ` (cost`. For the second line of the plan above it captures `Index Scan`, because ` using idx_orders_created_id` follows; for the first line it captures `Limit` (the regular expression lets the name absorb the extra space before `(cost`, and `.strip()` in the code removes it). The result is `('Limit', 'Index Scan')`. Notes such as `Filter:` do not match, since the colon is not a letter or space.
- `_INDEX = re.compile(r"(?:using|Bitmap Index Scan on) (\w+)")` captures the name after `using` (index scans, index-only scans) or after `Bitmap Index Scan on`: here `idx_orders_created_id`.
- `_REMOVED = re.compile(r"Rows Removed by Filter: (\d+)")` captures the number of discarded rows; this plan has no such line (the discarding is done by the index scan producing 200,000 rows, `rows=200000.00`), so it finds nothing and the sum is 0.
- `_HEAP_FETCHES = re.compile(r"Heap Fetches: (\d+)")` captures the number of table visits of an index-only scan: it is `0` in `e3_keyset_page10000_covering.txt`.

How the functions use them: `execution = _EXECUTION.search(text)` and `float(execution.group(1))`; `_REMOVED.findall(text)` returns every count and `sum(...)` adds them (a plan may have several filters). The `plan.py` module is the only place that reads plan text.

### In a test

`tests/e2e/test_replay_and_service.py`, lines 55 to 55:

```python
    assert re.search(r"ok postgres: [\d,]+ orders, pg_stat_statements loaded", result.stdout), result.stdout
```

`re.search(r"ok postgres: [\d,]+ orders, pg_stat_statements loaded", result.stdout)` checks the output of the health command without depending on the exact number of orders: `ok postgres: ` is literal, `[\d,]+` is one or more digits or commas (the number is printed with thousands separators, `1,000,000`), and ` orders, pg_stat_statements loaded` is literal. The test passes if the pattern is found anywhere in the output (`search`, not `match`).

## Try it yourself

1. `.venv/bin/python -c "import re; print(re.search(r'Execution Time: ([\d.]+) ms', open('sql/explain/e1_offset_page10000.txt').read()).group(1))"` prints `188.513` (or the figure in your current file).
2. `.venv/bin/python -c "import re; print(re.findall(r'(?:hit|read)=(\d+)', 'hit=2058 read=61692'))"` prints `['2058', '61692']`.
3. `.venv/bin/python -c "from busy_listing.domain.plan import _NODE; print(_NODE.findall(open('sql/explain/e1_offset_page10000.txt').read()))"` prints `['Limit ', 'Index Scan']`: the first name still has the trailing space that `parse_text_plan` strips.
4. `.venv/bin/python -c "from busy_listing.domain.plan import parse_text_plan; print(parse_text_plan(open('sql/explain/e1_offset_page10000.txt').read().splitlines()))"` prints `PlanSummary(execution_ms=188.513, pages=200751, node_types=('Limit', 'Index Scan'), index_names=('idx_orders_created_id',), rows_removed_by_filter=0, heap_fetches=None)`.
5. `.venv/bin/python -c "import re; print(re.search(r'Execution Time: (\d+) ms', open('sql/explain/e1_offset_page10000.txt').read()))"` prints `None`: without the dot in the character class, `\d+` cannot match `188.513` followed by ` ms`.

## Mistakes people make

- Forgetting the `r` prefix and having backslashes eaten by Python.
- Forgetting that `.` also matches a literal dot only by accident; to mean a dot, write `\.` (or `[.]`).
- Greedy matching more than intended (`.*` runs to the end of the line; `.*?` stops early).
- Using `match` (anchored at the start) where `search` was meant.
- Patterns that become unreadable; split them into named constants and test them.
- Using regex for the wrong job: JSON has `json.loads`.

**How this repository avoids them.** Patterns are compiled once as named constants; every pattern has a unit test with a realistic plan fragment (`tests/unit/domain/test_plan.py`); a plan without the expected line raises `PlanParseError` with a message instead of returning zero. JSON plans are read with real JSON parsing, not with regular expressions.

## Check yourself

1. What does `\d+` match? *One or more digits in a row.*
2. What is the difference between `(...)` and `(?:...)`? *The first remembers the matched text as a group; the second only groups.*
3. What does `findall` return for a pattern with one group? *A list of the texts matched by that group, one per match.*
4. Why write `r"\d"`? *A raw string keeps the backslash, so the regex engine receives `\d` intact.*
5. How do you match a literal dot? *`\.` or `[.]`.*

## Further reading

- Python `re` module (3.13): https://docs.python.org/3.13/library/re.html
- Regular Expression HOWTO: https://docs.python.org/3.13/howto/regex.html

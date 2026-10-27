"""What the lesson reads from a query plan: time, pages, node types, indexes and rows discarded.

Both plan formats are parsed here and nowhere else: the text of `EXPLAIN (ANALYZE, BUFFERS)` (what the
`.txt` files hold) and its JSON form (what the tests assert on). No I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import PlanParseError

_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")
_BUFFERS = re.compile(r"Buffers: shared (.*)")
_PAGE_COUNTS = re.compile(r"(?:hit|read)=(\d+)")
_NODE = re.compile(r"^\s*(?:->\s*)?([A-Z][A-Za-z ]+?)(?: using \w+| on \w+| \(cost)", re.MULTILINE)
_INDEX = re.compile(r"(?:using|Bitmap Index Scan on) (\w+)")
_REMOVED = re.compile(r"Rows Removed by Filter: (\d+)")
_HEAP_FETCHES = re.compile(r"Heap Fetches: (\d+)")


@dataclass(frozen=True, slots=True)
class PlanSummary:
    """One executed plan, reduced to the numbers the lesson compares."""

    execution_ms: float
    pages: int
    node_types: tuple[str, ...]
    index_names: tuple[str, ...]
    rows_removed_by_filter: int
    heap_fetches: int | None

    def has_node(self, node_type: str) -> bool:
        """True when any node of the plan has exactly this type, for example `Seq Scan` or `Sort`."""
        return node_type in self.node_types

    def uses_index(self, name: str) -> bool:
        """True when the plan reads the named index (index scan, index-only scan or bitmap index scan)."""
        return name in self.index_names


def parse_text_plan(lines: Sequence[str]) -> PlanSummary:
    """Summarize the text of an `EXPLAIN (ANALYZE, BUFFERS)` plan."""
    text = "\n".join(lines)
    execution = _EXECUTION.search(text)
    if execution is None:
        raise PlanParseError("no 'Execution Time' line: was the plan produced with ANALYZE?")
    heap_fetches = _HEAP_FETCHES.search(text)
    return PlanSummary(
        execution_ms=float(execution.group(1)),
        pages=pages_touched(lines),
        node_types=tuple(node.strip() for node in _NODE.findall(text)),
        index_names=tuple(dict.fromkeys(_INDEX.findall(text))),
        rows_removed_by_filter=sum(int(count) for count in _REMOVED.findall(text)),
        heap_fetches=int(heap_fetches.group(1)) if heap_fetches else None,
    )


def pages_touched(lines: Iterable[str]) -> int:
    """Pages a plan touched: the top node's `Buffers: shared hit=.. read=..`, plus the pages read to send the rows.

    The second figure is the `Buffers` line after `Serialization:`, where out-of-line (TOAST) values are fetched.
    """
    total, after_serialization = 0, False
    for line in lines:
        if line.startswith("Serialization:"):
            after_serialization = True
            continue
        match = _BUFFERS.search(line)
        if match and (after_serialization or total == 0):
            total += sum(int(count) for count in _PAGE_COUNTS.findall(match.group(1)))
            after_serialization = False
    return total


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

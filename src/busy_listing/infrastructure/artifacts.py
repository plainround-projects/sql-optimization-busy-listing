"""Adapter: the replay's evidence as files next to the queries. Implements `ArtifactStore`."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


class FileArtifactStore:
    """Writes `<name>.txt` plans and `results.md` into one directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def save_plan(self, name: str, lines: Sequence[str]) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        (self._directory / f"{name}.txt").write_text("\n".join(lines) + "\n")

    def save_report(self, text: str) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        (self._directory / "results.md").write_text(text)

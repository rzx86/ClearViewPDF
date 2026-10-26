"""Small JSON store for reading positions, bookmarks, and recent files."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Union

PathLike = Union[str, Path]


@dataclass(frozen=True)
class DocumentState:
    page_index: int = 0
    zoom: float = 1.0
    fit_mode: str = "width"
    rotation: int = 0


@dataclass(frozen=True)
class Bookmark:
    page_index: int
    title: str


class StateStore:
    """Persistent local state; no account, sync service, or network access."""

    def __init__(self, path: PathLike) -> None:
        self.path = Path(path)
        self._data = self._load()

    @staticmethod
    def _key(path: PathLike) -> str:
        return str(Path(path).expanduser().resolve())

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            data = {}
        return {
            "version": 1,
            "documents": data.get("documents", {}),
            "recents": data.get("recents", []),
            "bookmarks": data.get("bookmarks", {}),
            "preferences": data.get("preferences", {}),
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def document_state(self, path: PathLike) -> DocumentState:
        values = self._data["documents"].get(self._key(path), {})
        try:
            fit_mode = str(values.get("fit_mode", "width"))
            if fit_mode == "page":
                fit_mode = "height"
            return DocumentState(
                page_index=max(0, int(values.get("page_index", 0))),
                zoom=max(0.1, float(values.get("zoom", 1.0))),
                fit_mode=fit_mode,
                rotation=int(values.get("rotation", 0)) % 360,
            )
        except (TypeError, ValueError):
            return DocumentState()

    def remember_document(self, path: PathLike, state: DocumentState) -> None:
        self._data["documents"][self._key(path)] = asdict(state)
        self._save()

    def recent_files(self) -> list[str]:
        return list(self._data["recents"])

    def add_recent(self, path: PathLike) -> None:
        key = self._key(path)
        self._data["recents"] = [key] + [
            item for item in self._data["recents"] if item != key
        ][:9]
        self._save()

    def bookmarks(self, path: PathLike) -> list[Bookmark]:
        values = self._data["bookmarks"].get(self._key(path), [])
        return [
            Bookmark(page_index=int(item["page_index"]), title=str(item["title"]))
            for item in sorted(values, key=lambda item: item["page_index"])
        ]

    def add_bookmark(self, path: PathLike, page_index: int, title: str) -> None:
        key = self._key(path)
        bookmarks = [
            item
            for item in self._data["bookmarks"].get(key, [])
            if int(item["page_index"]) != page_index
        ]
        bookmarks.append({"page_index": page_index, "title": title})
        self._data["bookmarks"][key] = bookmarks
        self._save()

    def remove_bookmark(self, path: PathLike, page_index: int) -> None:
        key = self._key(path)
        self._data["bookmarks"][key] = [
            item
            for item in self._data["bookmarks"].get(key, [])
            if int(item["page_index"]) != page_index
        ]
        self._save()

    def preference(self, key: str, default: object = None) -> object:
        return self._data["preferences"].get(key, default)

    def set_preference(self, key: str, value: object) -> None:
        self._data["preferences"][key] = value
        self._save()

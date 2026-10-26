"""Whole-word text selection independent of the GUI toolkit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

Point = tuple[float, float]
Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class TextWord:
    rect: Rect
    text: str
    block: int
    line: int
    word: int


def _distance_squared(point: Point, rect: Rect) -> float:
    x, y = point
    x0, y0, x1, y1 = rect
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return dx * dx + dy * dy


def _nearest_index(words: Sequence[TextWord], point: Point) -> int:
    return min(
        range(len(words)),
        key=lambda index: (_distance_squared(point, words[index].rect), index),
    )


def select_words(
    words: Iterable[TextWord], start: Point, end: Point
) -> list[TextWord]:
    """Return the whole words between two drag endpoints in reading order."""

    ordered = sorted(words, key=lambda word: (word.block, word.line, word.word))
    if not ordered:
        return []
    first = _nearest_index(ordered, start)
    last = _nearest_index(ordered, end)
    if first > last:
        first, last = last, first
    return ordered[first : last + 1]


def words_to_text(words: Iterable[TextWord]) -> str:
    """Join selected words with spaces, preserving line and paragraph breaks."""

    lines: list[str] = []
    current_line: list[str] = []
    current_key: tuple[int, int] | None = None
    for word in words:
        key = (word.block, word.line)
        if current_key is not None and key != current_key:
            lines.append(" ".join(current_line))
            current_line = []
        current_line.append(word.text)
        current_key = key
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)

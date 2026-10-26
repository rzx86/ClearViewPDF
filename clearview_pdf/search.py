"""Hybrid document search built on MuPDF's text coordinates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pymupdf

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class SearchOptions:
    mode: str = "phrase"  # phrase, any, all
    match_case: bool = False
    whole_words: bool = False
    include_bookmarks: bool = False
    include_comments: bool = False
    include_attachments: bool = False
    proximity_pages: Optional[int] = None
    stemming: bool = False
    fuzzy: bool = False


@dataclass(frozen=True)
class SearchHit:
    page_index: int
    rect: Rect = (0.0, 0.0, 0.0, 0.0)
    rects: tuple[Rect, ...] = ()
    text: str = ""
    snippet: str = ""
    source: str = "text"
    attachment: str = ""
    start: int = -1
    end: int = -1
    word_start: int = -1
    word_end: int = -1
    distance: int = -1
    score: float = 0.0


@dataclass(frozen=True)
class DocumentSearchResult:
    path: str
    hits: list[SearchHit]
    error: str = ""


@dataclass(frozen=True)
class NearQuery:
    left: str
    right: str
    max_words: int = 50


def _hits_overlap(left: SearchHit, right: SearchHit) -> bool:
    if left.page_index != right.page_index:
        return False
    if min(left.word_start, left.word_end, right.word_start, right.word_end) >= 0:
        return left.word_start <= right.word_end and right.word_start <= left.word_end
    if min(left.start, right.start) >= 0 and left.end > left.start and right.end > right.start:
        return left.start < right.end and right.start < left.end
    return left.rect == right.rect and left.text == right.text


def merge_search_hits(text_hits, semantic_hits) -> list[SearchHit]:
    """Prefer precise text/fuzzy hits and add only non-overlapping semantic hits."""

    merged = list(text_hits)
    for candidate in semantic_hits:
        if any(_hits_overlap(existing, candidate) for existing in merged):
            continue
        merged.append(candidate)
    return merged


def parse_near_query(query: str) -> Optional[NearQuery]:
    """Parse only quoted operands, so an ordinary use of 'near' stays literal."""

    match = re.fullmatch(
        r'\s*"([^"]+)"\s+(?:near|\[\s*near\s*\])(?:/(\d+))?\s+"([^"]+)"\s*',
        query,
        re.IGNORECASE,
    )
    if not match:
        return None
    distance = int(match.group(2)) if match.group(2) else 50
    return NearQuery(match.group(1).strip(), match.group(3).strip(), max(0, distance))


def _pattern(query: str, options: SearchOptions) -> re.Pattern:
    expression = r"\s+".join(re.escape(part) for part in query.split())
    if options.whole_words:
        expression = rf"(?<!\w)(?:{expression})(?!\w)"
    return re.compile(expression, 0 if options.match_case else re.IGNORECASE)


def _page_text_and_words(page):
    words = sorted(
        page.get_text("words", sort=False),
        key=lambda word: (word[5], word[6], word[7]),
    )
    parts: list[str] = []
    character_words: list[Optional[int]] = []
    for index, word in enumerate(words):
        if parts:
            parts.append(" ")
            character_words.append(None)
        parts.append(word[4])
        character_words.extend([index] * len(word[4]))
    return "".join(parts), words, character_words


def _word_offsets(words) -> list[tuple[int, int]]:
    offsets = []
    position = 0
    for index, word in enumerate(words):
        if index:
            position += 1
        start = position
        position += len(word[4])
        offsets.append((start, position))
    return offsets


def _line_rectangles(selected_words) -> tuple[Rect, ...]:
    groups: list[tuple[tuple[int, int], list]] = []
    for word in selected_words:
        key = (word[5], word[6])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(word)
    rectangles = []
    for _, group in groups:
        rect = pymupdf.Rect(group[0][:4])
        for word in group[1:]:
            rect.include_rect(pymupdf.Rect(word[:4]))
        rectangles.append(tuple(rect))
    return tuple(rectangles)


def _make_hit(
    page_index: int,
    text: str,
    words,
    indexes: list[int],
    start: int,
    end: int,
    matched_text: str,
    source: str = "text",
) -> SearchHit:
    selected = [words[index] for index in indexes]
    rectangles = _line_rectangles(selected)
    before = text[max(0, start - 60):start].strip()
    after = text[end:end + 60].strip()
    return SearchHit(
        page_index=page_index,
        rect=rectangles[0],
        rects=rectangles,
        text=matched_text,
        snippet=f"{before} {matched_text} {after}".strip(),
        source=source,
        start=start,
        end=end,
        word_start=min(indexes),
        word_end=max(indexes),
    )


def _exact_hits(page, page_index: int, query: str, options: SearchOptions, prepared=None):
    text, words, character_words = prepared or _page_text_and_words(page)
    if not text:
        return []
    hits = []
    for match in _pattern(query, options).finditer(text):
        indexes = sorted({
            index for index in character_words[match.start():match.end()] if index is not None
        })
        if indexes:
            hits.append(_make_hit(
                page_index, text, words, indexes, match.start(), match.end(), match.group(0)
            ))
    return hits


def _normal_word(word: str, match_case: bool) -> str:
    word = word.strip("\"'“”‘’.,;:!?()[]{}<>")
    return word if match_case else word.casefold()


def _edit_distance(left: str, right: str, limit: int) -> int:
    """Levenshtein distance with an early cutoff; returns limit + 1 if above it."""

    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for row, left_character in enumerate(left, 1):
        current = [row]
        for column, right_character in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_character != right_character),
            ))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _allowed_edits(term: str) -> int:
    if len(term) <= 4:
        return 0
    return 1 if len(term) <= 8 else 2


def _fuzzy_hits(page, page_index: int, query: str, options: SearchOptions, prepared=None):
    text, words, _ = prepared or _page_text_and_words(page)
    terms = query.split()
    if not text or not terms or len(terms) > len(words):
        return []
    offsets = _word_offsets(words)
    hits = []
    for first in range(len(words) - len(terms) + 1):
        total_edits = 0
        for offset, term in enumerate(terms):
            candidate = _normal_word(words[first + offset][4], options.match_case)
            expected = _normal_word(term, options.match_case)
            allowed = _allowed_edits(expected)
            distance = _edit_distance(expected, candidate, allowed)
            if distance > allowed:
                break
            total_edits += distance
        else:
            indexes = list(range(first, first + len(terms)))
            start = offsets[first][0]
            end = offsets[indexes[-1]][1]
            hit = _make_hit(
                page_index, text, words, indexes, start, end, text[start:end]
            )
            hits.append(SearchHit(
                **{**hit.__dict__, "score": 1.0 / (1.0 + total_edits)}
            ))
    return hits


def _matching_hits(page, page_index: int, query: str, options: SearchOptions, prepared=None):
    hits = _exact_hits(page, page_index, query, options, prepared)
    if options.fuzzy:
        hits.extend(_fuzzy_hits(page, page_index, query, options, prepared))
    unique = {}
    for hit in hits:
        key = (hit.start, hit.end)
        if key not in unique or hit.score > unique[key].score:
            unique[key] = hit
    return sorted(unique.values(), key=lambda hit: hit.start)


def _word_distance(left: SearchHit, right: SearchHit) -> int:
    if left.word_end < right.word_start:
        return right.word_start - left.word_end - 1
    if right.word_end < left.word_start:
        return left.word_start - right.word_end - 1
    return 0


def _near_hits(document, query: NearQuery, options: SearchOptions) -> list[SearchHit]:
    results = []
    for page_index in range(document.page_count):
        page = document.page(page_index)
        prepared = _page_text_and_words(page)
        text = prepared[0]
        left_hits = _matching_hits(page, page_index, query.left, options, prepared)
        right_hits = _matching_hits(page, page_index, query.right, options, prepared)
        for left in left_hits:
            candidates = []
            for right in right_hits:
                distance = _word_distance(left, right)
                if distance <= query.max_words:
                    candidates.append((distance, abs(left.start - right.start), right))
            if not candidates:
                continue
            distance, _, right = min(candidates, key=lambda item: (item[0], item[1]))
            first, second = sorted((left, right), key=lambda hit: hit.start)
            rectangles = tuple(sorted(
                left.rects + right.rects, key=lambda rect: (rect[1], rect[0])
            ))
            start, end = first.start, second.end
            results.append(SearchHit(
                page_index=page_index,
                rect=rectangles[0],
                rects=rectangles,
                text=f"{left.text} … {right.text}",
                snippet=text[max(0, start - 40):min(len(text), end + 40)].strip(),
                source="near",
                start=start,
                end=end,
                word_start=min(left.word_start, right.word_start),
                word_end=max(left.word_end, right.word_end),
                distance=distance,
                score=1.0 / (1.0 + distance),
            ))
    results.sort(key=lambda hit: (hit.page_index, hit.start, hit.distance))
    return results


def _content_matches(content: str, query: str, options: SearchOptions) -> bool:
    terms = list(dict.fromkeys(query.split()))
    if options.mode == "phrase":
        return _pattern(query, options).search(content) is not None
    matches = (_pattern(term, options).search(content) is not None for term in terms)
    return any(matches) if options.mode == "any" else all(matches)


def search_document(
    document, query: str, options: Optional[SearchOptions] = None
) -> list[SearchHit]:
    options = options or SearchOptions()
    query = query.strip()
    if not query:
        return []
    near = parse_near_query(query)
    if near is not None:
        return _near_hits(document, near, options)
    hits: list[SearchHit] = []
    terms = list(dict.fromkeys(query.split()))
    for page_index in range(document.page_count):
        page = document.page(page_index)
        prepared = _page_text_and_words(page)
        if options.mode == "phrase":
            hits.extend(_matching_hits(page, page_index, query, options, prepared))
            continue
        per_term = [_matching_hits(page, page_index, term, options, prepared) for term in terms]
        if options.mode == "any" or (options.mode == "all" and all(per_term)):
            for term_hits in per_term:
                hits.extend(term_hits)
    if options.include_bookmarks:
        for entry in document.outline():
            if entry.page_index is not None and _content_matches(entry.title, query, options):
                hits.append(SearchHit(
                    page_index=entry.page_index,
                    text=entry.title,
                    snippet=entry.title,
                    source="bookmark",
                ))
    if options.include_comments:
        for page_index in range(document.page_count):
            annotations = document.page(page_index).annots()
            for annotation in annotations or []:
                content = annotation.info.get("content", "")
                if _content_matches(content, query, options):
                    rect = tuple(annotation.rect)
                    hits.append(SearchHit(
                        page_index=page_index,
                        rect=rect,
                        rects=(rect,),
                        text=annotation.type[1],
                        snippet=content,
                        source="comment",
                    ))
    hits.sort(key=lambda hit: (hit.page_index, hit.rect[1], hit.rect[0]))
    return hits

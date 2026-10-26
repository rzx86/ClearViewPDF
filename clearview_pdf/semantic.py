"""Local, embedding-based semantic and semantic-proximity search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from .search import (
    Rect,
    SearchHit,
    SearchOptions,
    _line_rectangles,
    _matching_hits,
    _page_text_and_words,
    _word_distance,
    _word_offsets,
    parse_near_query,
)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


@dataclass(frozen=True)
class Passage:
    page_index: int
    word_start: int
    word_end: int
    start: int
    end: int
    text: str
    rects: tuple[Rect, ...]


@dataclass
class DocumentIndex:
    passages: list[Passage]
    vectors: np.ndarray
    spans: list[Passage]
    span_vectors: np.ndarray
    page_texts: list[str]


@dataclass(frozen=True)
class _Candidate:
    page_index: int
    word_start: int
    word_end: int
    start: int
    end: int
    text: str
    rects: tuple[Rect, ...]
    score: float


class LocalEmbeddingModel:
    """FastEmbed/ONNX backend; downloads the model only on first use."""

    def __init__(self, cache_dir: Path, model_name: str = DEFAULT_MODEL) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(cache_dir))

    @staticmethod
    def _array(values) -> np.ndarray:
        if isinstance(values, np.ndarray):
            return values
        return np.asarray(list(values), dtype=np.float32)

    def embed(self, texts: list[str]) -> np.ndarray:
        return self._array(self._model.embed(texts))

    def query_embed(self, texts: list[str]) -> np.ndarray:
        return self._array(self._model.query_embed(texts))


def build_passages(document, window: int = 48, stride: int = 24) -> list[Passage]:
    passages = []
    for page_index in range(document.page_count):
        _, words, _ = _page_text_and_words(document.page(page_index))
        if not words:
            continue
        offsets = _word_offsets(words)
        if len(words) <= window:
            starts = [0]
        else:
            starts = list(range(0, len(words) - window + 1, stride))
            last_start = len(words) - window
            if starts[-1] != last_start:
                starts.append(last_start)
        for first in starts:
            last = min(first + window, len(words)) - 1
            selected = words[first:last + 1]
            start = offsets[first][0]
            end = offsets[last][1]
            passages.append(Passage(
                page_index=page_index,
                word_start=first,
                word_end=last,
                start=start,
                end=end,
                text=" ".join(word[4] for word in selected),
                rects=_line_rectangles(selected),
            ))
    return passages


def _scores(vectors: np.ndarray, query: np.ndarray) -> np.ndarray:
    if not len(vectors):
        return np.asarray([])
    vectors = np.asarray(vectors, dtype=np.float32)
    query = np.asarray(query, dtype=np.float32)
    denominator = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query)
    denominator = np.where(denominator == 0, 1, denominator)
    return (vectors @ query) / denominator


def _distinct_hits(hits: list[SearchHit], limit: int) -> list[SearchHit]:
    """Suppress overlapping windows so one passage appears only once."""

    distinct = []
    for hit in hits:
        if any(
            hit.page_index == other.page_index
            and max(hit.word_start, other.word_start) <= min(hit.word_end, other.word_end)
            for other in distinct
        ):
            continue
        distinct.append(hit)
        if len(distinct) == limit:
            break
    return distinct


class SemanticEngine:
    """One two-resolution index shared by semantic and semantic-near queries."""

    def __init__(self, model) -> None:
        self.model = model
        self._index_key = None
        self._index: Optional[DocumentIndex] = None

    def _get_index(self, document) -> DocumentIndex:
        stat = document.path.stat()
        key = (str(document.path), stat.st_size, stat.st_mtime_ns)
        if self._index_key == key and self._index is not None:
            return self._index
        passages = build_passages(document, window=48, stride=24)
        spans = build_passages(document, window=8, stride=4)
        texts = [passage.text for passage in passages + spans]
        vectors = self.model.embed(texts) if texts else np.empty((0, 0))
        page_texts = [
            _page_text_and_words(document.page(page_index))[0]
            for page_index in range(document.page_count)
        ]
        self._index = DocumentIndex(
            passages=passages,
            vectors=vectors[:len(passages)],
            spans=spans,
            span_vectors=vectors[len(passages):],
            page_texts=page_texts,
        )
        self._index_key = key
        return self._index

    @staticmethod
    def _passage_hit(passage: Passage, score: float) -> SearchHit:
        return SearchHit(
            page_index=passage.page_index,
            rect=passage.rects[0],
            rects=passage.rects,
            text=f"{score:.0%} semantic match",
            snippet=passage.text,
            source="semantic",
            start=passage.start,
            end=passage.end,
            word_start=passage.word_start,
            word_end=passage.word_end,
            score=float(score),
        )

    def search(self, document, query: str, limit: int = 20) -> list[SearchHit]:
        query = query.strip()
        if not query:
            return []
        index = self._get_index(document)
        near = parse_near_query(query)
        if near is not None:
            return self._semantic_near(document, index, near, limit)
        if not index.passages:
            return []
        query_vector = self.model.query_embed([query])[0]
        scores = _scores(index.vectors, query_vector)
        order = np.argsort(-scores)
        ranked = [self._passage_hit(index.passages[position], scores[position]) for position in order]
        return _distinct_hits(ranked, limit)

    @staticmethod
    def _exact_candidates(document, page_index: int, query: str) -> list[_Candidate]:
        hits = _matching_hits(
            document.page(page_index), page_index, query, SearchOptions(fuzzy=True)
        )
        return [_Candidate(
            page_index=hit.page_index,
            word_start=hit.word_start,
            word_end=hit.word_end,
            start=hit.start,
            end=hit.end,
            text=hit.text,
            rects=hit.rects,
            score=1.0,
        ) for hit in hits]

    def _semantic_near(self, document, index: DocumentIndex, near, limit: int):
        if not index.spans:
            return []
        left_vector, right_vector = self.model.query_embed([near.left, near.right])
        left_scores = _scores(index.span_vectors, left_vector)
        right_scores = _scores(index.span_vectors, right_vector)
        candidates: dict[int, tuple[list[_Candidate], list[_Candidate]]] = {}
        for page_index in range(document.page_count):
            positions = [
                position for position, span in enumerate(index.spans)
                if span.page_index == page_index
            ]
            left: list[_Candidate] = []
            right: list[_Candidate] = []
            for positions_for_side, scores, output in (
                (positions, left_scores, left), (positions, right_scores, right)
            ):
                ranked = sorted(positions_for_side, key=lambda pos: -scores[pos])[:4]
                for position in ranked:
                    span = index.spans[position]
                    output.append(_Candidate(
                        page_index=span.page_index,
                        word_start=span.word_start,
                        word_end=span.word_end,
                        start=span.start,
                        end=span.end,
                        text=span.text,
                        rects=span.rects,
                        score=float(scores[position]),
                    ))
            left.extend(self._exact_candidates(document, page_index, near.left))
            right.extend(self._exact_candidates(document, page_index, near.right))
            candidates[page_index] = (left, right)

        best = {}
        for page_index, (left_candidates, right_candidates) in candidates.items():
            page_text = index.page_texts[page_index]
            for left in left_candidates:
                for right in right_candidates:
                    distance = _word_distance(left, right)
                    if distance > near.max_words:
                        continue
                    start = min(left.start, right.start)
                    end = max(left.end, right.end)
                    score = max(0.0, (left.score + right.score) / 2 - distance * 0.002)
                    if score <= 0:
                        continue
                    key = (page_index, start, end)
                    if key in best and best[key].score >= score:
                        continue
                    rectangles = tuple(sorted(
                        left.rects + right.rects, key=lambda rect: (rect[1], rect[0])
                    ))
                    best[key] = SearchHit(
                        page_index=page_index,
                        rect=rectangles[0],
                        rects=rectangles,
                        text=f"{left.text} … {right.text}",
                        snippet=page_text[max(0, start - 40):min(len(page_text), end + 40)].strip(),
                        source="semantic-near",
                        start=start,
                        end=end,
                        word_start=min(left.word_start, right.word_start),
                        word_end=max(left.word_end, right.word_end),
                        distance=distance,
                        score=score,
                    )
        ranked = sorted(best.values(), key=lambda hit: -hit.score)
        return _distinct_hits(ranked, limit)

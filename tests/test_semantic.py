from pathlib import Path

import numpy as np
import pymupdf

from clearview_pdf.document import PDFDocument
from clearview_pdf.semantic import SemanticEngine, build_passages


class FakeModel:
    """Deterministic concept vectors for testing ranking without downloads."""

    def _vectors(self, texts):
        rows = []
        for text in texts:
            lowered = text.lower()
            vector = np.zeros(3)
            if any(term in lowered for term in ["gqa", "grouped", "transformer", "cat", "feline"]):
                vector[0] = 1
            if any(term in lowered for term in ["pet", "animal"]):
                vector[1] = 1
            if any(term in lowered for term in ["brownie", "chocolate"]):
                vector[2] = 1
            if not vector.any():
                vector[2] = 0.01
            rows.append(vector / np.linalg.norm(vector))
        return np.array(rows)

    def embed(self, texts):
        return self._vectors(texts)

    def query_embed(self, texts):
        return self._vectors(texts)


def make_pdf(path: Path, texts: list[str]) -> Path:
    document = pymupdf.open()
    for text in texts:
        page = document.new_page(width=500, height=700)
        page.insert_textbox(pymupdf.Rect(40, 40, 460, 660), text, fontsize=12)
    document.save(path)
    document.close()
    return path


def test_passages_retain_page_word_and_rectangle_locations(tmp_path):
    path = make_pdf(tmp_path / "passages.pdf", ["one two three four five six"])
    with PDFDocument.open(path) as document:
        passages = build_passages(document, window=4, stride=2)
        assert [passage.word_start for passage in passages] == [0, 2]
        assert passages[0].page_index == 0
        assert passages[0].rects
        assert passages[0].text == "one two three four"
        assert passages[-1].text == "three four five six"


def test_semantic_search_ranks_concept_matches_without_keyword_match(tmp_path):
    path = make_pdf(
        tmp_path / "semantic.pdf",
        ["Transformer inference uses grouped query attention.", "Chocolate brownie recipe"],
    )
    with PDFDocument.open(path) as document:
        engine = SemanticEngine(FakeModel())
        hits = engine.search(document, "talks about GQA")
        assert hits[0].page_index == 0
        assert hits[0].source == "semantic"
        assert hits[0].score > hits[1].score


def test_semantic_search_collapses_overlapping_duplicate_passages(tmp_path):
    text = " ".join(["transformer"] * 60)
    path = make_pdf(tmp_path / "duplicates.pdf", [text])
    with PDFDocument.open(path) as document:
        engine = SemanticEngine(FakeModel())
        hits = engine.search(document, "talks about GQA")
        assert len(hits) == 1


def test_semantic_near_finds_concepts_and_enforces_positions(tmp_path):
    text = "cat sat with animals " + " ".join(["quiet"] * 20)
    path = make_pdf(tmp_path / "semantic-near.pdf", [text])
    with PDFDocument.open(path) as document:
        engine = SemanticEngine(FakeModel())
        hits = engine.search(document, '"felines" near/20 "pets"')
        assert len(hits) == 1
        assert hits[0].source == "semantic-near"
        assert hits[0].page_index == 0
        assert hits[0].distance >= 0

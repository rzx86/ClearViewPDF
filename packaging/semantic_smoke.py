"""Real-model Windows smoke test; uses the same cache as the packaged reader."""

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

from clearview_pdf.document import PDFDocument
from clearview_pdf.search import SearchOptions, merge_search_hits
from clearview_pdf.semantic import LocalEmbeddingModel, SemanticEngine


def main() -> None:
    app = QApplication([])
    app.setApplicationName("ClearView PDF")
    app.setOrganizationName("ClearView")
    root = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    ))
    cache = root / "semantic-models"
    print(f"MODEL_CACHE={cache}")
    engine = SemanticEngine(LocalEmbeddingModel(cache))
    sample = Path(__file__).resolve().parents[1] / "samples" / "semantic-smoke.pdf"
    with PDFDocument.open(sample) as document:
        hits = engine.search(document, "talks about GQA")
        near = engine.search(document, '"attention" near/20 "memory"')
    print("SEMANTIC_RESULTS", [(hit.source, round(hit.score, 3)) for hit in hits])
    print("NEAR_RESULTS", [(hit.source, hit.distance) for hit in near])
    assert hits and hits[0].source == "semantic"
    assert near and near[0].distance <= 20

    hybrid_sample = sample.with_name("hybrid-smoke.pdf")
    with PDFDocument.open(hybrid_sample) as document:
        text_hits = document.search("Serchable", SearchOptions(fuzzy=True))
        semantic_hits = engine.search(document, "Serchable")
        hybrid = merge_search_hits(text_hits, semantic_hits)
    print("HYBRID_RESULTS", [(hit.page_index, hit.source) for hit in hybrid])
    assert [(hit.page_index, hit.source) for hit in hybrid] == [
        (0, "text"),
        (1, "semantic"),
    ]


if __name__ == "__main__":
    main()

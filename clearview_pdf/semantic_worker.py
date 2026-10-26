"""Background semantic searches; each worker opens its own MuPDF document."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal, Slot

from .document import PDFDocument
from .semantic import SemanticEngine


class SemanticSearchWorker(QObject):
    finished = Signal(object, object)  # hits, reusable engine
    failed = Signal(str)

    def __init__(
        self,
        path: Path,
        password: Optional[str],
        query: str,
        model_factory,
        cache_dir: Path,
        engine: Optional[SemanticEngine] = None,
    ) -> None:
        super().__init__()
        self.path = path
        self.password = password
        self.query = query
        self.model_factory = model_factory
        self.cache_dir = cache_dir
        self.engine = engine

    @staticmethod
    def _cancelled() -> bool:
        return QThread.currentThread().isInterruptionRequested()

    @Slot()
    def run(self) -> None:
        try:
            if self._cancelled():
                self.finished.emit([], self.engine)
                return
            engine = self.engine
            if engine is None:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                engine = SemanticEngine(self.model_factory(self.cache_dir))
            if self._cancelled():
                self.finished.emit([], engine)
                return
            with PDFDocument.open(self.path, password=self.password) as document:
                hits = engine.search(document, self.query)
            if self._cancelled():
                hits = []
            self.finished.emit(hits, engine)
        except Exception as exc:  # surfaced in the search bar, never a modal crash
            self.failed.emit(str(exc) or exc.__class__.__name__)

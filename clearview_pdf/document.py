"""Document access for ClearView PDF.

This module deliberately contains no Qt code, so file handling and rendering can
be tested independently from the interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import pymupdf

from .search import SearchHit, SearchOptions, search_document


class DocumentError(RuntimeError):
    """A PDF could not be opened or read."""


class PasswordRequired(DocumentError):
    """The document needs a password before its contents can be accessed."""


class InvalidPassword(DocumentError):
    """The supplied password did not unlock the document."""


@dataclass(frozen=True)
class OutlineItem:
    level: int
    title: str
    page_index: Optional[int]


class PDFDocument:
    """An open MuPDF document with a small, stable API for the reader."""

    def __init__(self, path: Path, document: pymupdf.Document) -> None:
        self.path = path
        self._document = document

    @classmethod
    def open(
        cls, path: Union[str, Path], password: Optional[str] = None
    ) -> "PDFDocument":
        pdf_path = Path(path).expanduser().resolve()
        try:
            document = pymupdf.open(pdf_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DocumentError(f"Could not open {pdf_path}: {exc}") from exc

        if document.needs_pass:
            if password is None:
                document.close()
                raise PasswordRequired("This PDF is password protected.")
            if not document.authenticate(password):
                document.close()
                raise InvalidPassword("That password did not unlock the PDF.")
        return cls(pdf_path, document)

    @property
    def page_count(self) -> int:
        return self._document.page_count

    def page(self, index: int) -> pymupdf.Page:
        if not 0 <= index < self.page_count:
            raise IndexError(f"Page index {index} is outside this document")
        return self._document.load_page(index)

    def page_text(self, index: int) -> str:
        return self.page(index).get_text("text")

    def page_size(self, index: int, rotation: int = 0) -> tuple[float, float]:
        if rotation % 90:
            raise ValueError("Rotation must be a multiple of 90 degrees")
        rect = self.page(index).rect
        if rotation % 180:
            return (rect.height, rect.width)
        return (rect.width, rect.height)

    def render_page(
        self, index: int, zoom: float = 1.0, rotation: int = 0
    ) -> pymupdf.Pixmap:
        if zoom <= 0:
            raise ValueError("Zoom must be positive")
        if rotation % 90:
            raise ValueError("Rotation must be a multiple of 90 degrees")
        matrix = pymupdf.Matrix(zoom, zoom).prerotate(rotation)
        return self.page(index).get_pixmap(matrix=matrix, alpha=False, annots=True)

    def search(
        self, query: str, options: Optional[SearchOptions] = None
    ) -> list[SearchHit]:
        return search_document(self, query, options)

    def outline(self) -> list[OutlineItem]:
        return [
            OutlineItem(level, title, page_number - 1 if page_number > 0 else None)
            for level, title, page_number in self._document.get_toc(simple=True)
        ]

    def close(self) -> None:
        self._document.close()

    def __enter__(self) -> "PDFDocument":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

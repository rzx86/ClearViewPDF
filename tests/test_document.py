from pathlib import Path

import pymupdf as fitz
import pytest

from clearview_pdf.document import InvalidPassword, PasswordRequired, PDFDocument


def make_pdf(path: Path, pages: int = 3) -> Path:
    doc = fitz.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=400, height=600)
        page.insert_text((48, 72), f"ClearView reading sample {number}", fontsize=14)
        page.insert_text((48, 108), "Searchable text and selectable words.", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_open_extract_and_render_pdf(tmp_path):
    path = make_pdf(tmp_path / "sample.pdf")

    with PDFDocument.open(path) as document:
        assert document.page_count == 3
        assert "reading sample 2" in document.page_text(1)
        assert document.page_size(0) == (400, 600)
        pixmap = document.render_page(0, zoom=1.5)
        assert (pixmap.width, pixmap.height) == (600, 900)


def test_search_returns_every_match_with_its_page_and_rectangle(tmp_path):
    path = make_pdf(tmp_path / "sample.pdf")

    with PDFDocument.open(path) as document:
        hits = document.search("SEARCHABLE")
        assert [hit.page_index for hit in hits] == [0, 1, 2]
        assert len(hits[0].rect) == 4
        assert hits[0].rect[1] > 0
        assert document.search("") == []


def test_encrypted_pdf_requires_the_correct_password(tmp_path):
    path = tmp_path / "locked.pdf"
    document = fitz.open()
    document.new_page()
    document.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="reader",
        owner_pw="owner",
    )
    document.close()

    with pytest.raises(PasswordRequired):
        PDFDocument.open(path)
    with pytest.raises(InvalidPassword):
        PDFDocument.open(path, password="wrong")
    with PDFDocument.open(path, password="reader") as unlocked:
        assert unlocked.page_count == 1


def test_outline_preserves_hierarchy_and_uses_zero_based_pages(tmp_path):
    path = make_pdf(tmp_path / "outlined.pdf")
    document = fitz.open(path)
    document.set_toc([[1, "Chapter One", 1], [2, "A Section", 2]])
    document.saveIncr()
    document.close()

    with PDFDocument.open(path) as document:
        outline = document.outline()
        assert [(item.level, item.title, item.page_index) for item in outline] == [
            (1, "Chapter One", 0),
            (2, "A Section", 1),
        ]

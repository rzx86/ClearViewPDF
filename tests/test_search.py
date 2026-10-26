from pathlib import Path

import pymupdf

from clearview_pdf.search import SearchOptions, search_document


def make_pdf(path: Path, page_texts: list[str]) -> Path:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page(width=500, height=700)
        page.insert_textbox(
            pymupdf.Rect(40, 40, 460, 660), text, fontsize=12, lineheight=1.4
        )
    document.save(path)
    document.close()
    return path


def open_pdf(path: Path):
    from clearview_pdf.document import PDFDocument

    return PDFDocument.open(path)


def test_case_sensitive_and_whole_word_matching(tmp_path):
    path = make_pdf(tmp_path / "words.pdf", ["Read reader read READ reading"])
    with open_pdf(path) as document:
        assert len(search_document(document, "read")) == 5
        whole = SearchOptions(whole_words=True)
        assert len(search_document(document, "read", whole)) == 3
        exact = SearchOptions(whole_words=True, match_case=True)
        hits = search_document(document, "read", exact)
        assert len(hits) == 1
        assert hits[0].text == "read"
        assert hits[0].snippet


def test_exact_phrase_is_one_result_with_highlight_rectangles(tmp_path):
    path = make_pdf(tmp_path / "phrase.pdf", ["A searchable phrase\nacross two lines"])
    with open_pdf(path) as document:
        hits = search_document(document, "searchable phrase across")
        assert len(hits) == 1
        assert hits[0].text == "searchable phrase across"
        assert len(hits[0].rects) >= 2
        assert hits[0].source == "text"


def test_any_word_and_all_words_modes(tmp_path):
    path = make_pdf(
        tmp_path / "modes.pdf",
        ["alpha beta alpha", "alpha only", "beta only"],
    )
    with open_pdf(path) as document:
        any_hits = search_document(
            document, "alpha beta", SearchOptions(mode="any")
        )
        assert [hit.page_index for hit in any_hits] == [0, 0, 0, 1, 2]

        all_hits = search_document(
            document, "alpha beta", SearchOptions(mode="all")
        )
        assert [hit.page_index for hit in all_hits] == [0, 0, 0]
        assert {hit.text for hit in all_hits} == {"alpha", "beta"}


def test_search_can_include_bookmarks_and_comments(tmp_path):
    path = make_pdf(tmp_path / "extras.pdf", ["Visible body text"])
    document = pymupdf.open(path)
    document.set_toc([[1, "Searchable bookmark", 1]])
    document[0].add_text_annot((50, 150), "Searchable comment")
    document.saveIncr()
    document.close()

    options = SearchOptions(include_bookmarks=True, include_comments=True)
    with open_pdf(path) as document:
        hits = search_document(document, "searchable", options)
        assert {hit.source for hit in hits} == {"bookmark", "comment"}
        assert all(hit.page_index == 0 for hit in hits)
        assert all("Searchable" in hit.snippet for hit in hits)


def test_near_operator_enforces_word_distance_and_highlights_both_terms(tmp_path):
    path = make_pdf(
        tmp_path / "near.pdf",
        ["alpha one two beta", "alpha one two three four five beta"],
    )
    with open_pdf(path) as document:
        hits = search_document(document, '"alpha" near/3 "beta"')
        assert len(hits) == 1
        assert hits[0].page_index == 0
        assert hits[0].distance == 2
        assert hits[0].source == "near"
        assert len(hits[0].rects) == 2
        assert "alpha one two beta" in hits[0].snippet

        bracketed = search_document(document, '"alpha" [near] "beta"')
        assert len(bracketed) == 2
        assert search_document(document, "alpha near beta") == []


def test_fuzzy_matching_tolerates_typos_but_not_short_acronym_drift(tmp_path):
    path = make_pdf(tmp_path / "fuzzy.pdf", ["Grouped query attention. GQA is not GOA."])
    with open_pdf(path) as document:
        fuzzy = SearchOptions(fuzzy=True)
        hits = search_document(document, "gruped", fuzzy)
        assert len(hits) == 1
        assert hits[0].text == "Grouped"

        acronym = search_document(document, "GQA", fuzzy)
        assert len(acronym) == 1
        assert acronym[0].text == "GQA"


def test_hybrid_merge_keeps_text_and_nonduplicate_semantic_hits():
    from clearview_pdf.search import SearchHit, merge_search_hits

    text = SearchHit(
        page_index=0, start=0, end=10, word_start=0, word_end=0, source="text"
    )
    overlapping_semantic = SearchHit(
        page_index=0, start=0, end=100, word_start=0, word_end=10, source="semantic"
    )
    other_semantic = SearchHit(
        page_index=1, start=0, end=100, word_start=0, word_end=10, source="semantic"
    )

    merged = merge_search_hits([text], [overlapping_semantic, other_semantic])

    assert merged == [text, other_semantic]

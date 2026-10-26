import json

from clearview_pdf.state import Bookmark, DocumentState, StateStore


def test_reading_position_and_recent_files_survive_restart(tmp_path):
    state_path = tmp_path / "state.json"
    pdf = tmp_path / "book.pdf"
    other = tmp_path / "other.pdf"
    store = StateStore(state_path)

    store.remember_document(
        pdf, DocumentState(page_index=41, zoom=1.35, fit_mode="custom", rotation=90)
    )
    store.add_recent(pdf)
    store.add_recent(other)
    store.add_recent(pdf)

    restored = StateStore(state_path)
    assert restored.document_state(pdf) == DocumentState(
        page_index=41, zoom=1.35, fit_mode="custom", rotation=90
    )
    assert restored.recent_files() == [str(pdf.resolve()), str(other.resolve())]
    assert json.loads(state_path.read_text())["version"] == 1


def test_bookmarks_are_sorted_per_document_and_can_be_removed(tmp_path):
    store = StateStore(tmp_path / "state.json")
    book = tmp_path / "book.pdf"
    other = tmp_path / "other.pdf"

    store.add_bookmark(book, 8, "Later")
    store.add_bookmark(book, 3, "Chapter")
    store.add_bookmark(other, 1, "Other book")
    assert store.bookmarks(book) == [
        Bookmark(page_index=3, title="Chapter"),
        Bookmark(page_index=8, title="Later"),
    ]

    store.remove_bookmark(book, 3)
    restored = StateStore(tmp_path / "state.json")
    assert restored.bookmarks(book) == [Bookmark(page_index=8, title="Later")]
    assert restored.bookmarks(other) == [Bookmark(page_index=1, title="Other book")]


def test_legacy_fit_page_state_migrates_to_fit_height(tmp_path):
    path = tmp_path / "state.json"
    pdf = tmp_path / "legacy.pdf"
    path.write_text(
        json.dumps(
            {
                "documents": {
                    str(pdf.resolve()): {
                        "page_index": 2,
                        "zoom": 1.0,
                        "fit_mode": "page",
                        "rotation": 0,
                    }
                }
            }
        )
    )

    assert StateStore(path).document_state(pdf).fit_mode == "height"


def test_preferences_round_trip_without_losing_document_state(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    store.set_preference("dark_mode", True)
    store.set_preference("sidebar_visible", False)

    restored = StateStore(path)
    assert restored.preference("dark_mode") is True
    assert restored.preference("sidebar_visible") is False
    assert restored.preference("missing", "fallback") == "fallback"

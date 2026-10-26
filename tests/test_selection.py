from clearview_pdf.selection import TextWord, select_words, words_to_text


WORDS = [
    TextWord((0, 0, 20, 10), "One", 0, 0, 0),
    TextWord((25, 0, 45, 10), "two", 0, 0, 1),
    TextWord((0, 15, 35, 25), "three", 0, 1, 0),
    TextWord((40, 15, 60, 25), "four", 0, 1, 1),
]


def test_drag_selects_words_in_reading_order_in_either_direction():
    forward = select_words(WORDS, start=(30, 5), end=(45, 20))
    reverse = select_words(WORDS, start=(45, 20), end=(30, 5))

    assert [word.text for word in forward] == ["two", "three", "four"]
    assert forward == reverse
    assert words_to_text(forward) == "two\nthree four"


def test_selection_outside_text_is_empty():
    assert select_words([], start=(0, 0), end=(10, 10)) == []
    assert words_to_text([]) == ""

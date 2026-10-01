import pytest

from stages.selection import new_keywords, parse_selection


@pytest.mark.parametrize("text, n, want", [
    ("1-10", 14, list(range(1, 11))),
    ("1,3,5-7", 14, [1, 3, 5, 6, 7]),
    ("1-12 drop 4,7", 14, [1, 2, 3, 5, 6, 8, 9, 10, 11, 12]),
    ("all", 9, list(range(1, 10))),
    ("all drop 2", 9, [1, 3, 4, 5, 6, 7, 8, 9]),
    ("1-5, 8 9", 12, [1, 2, 3, 4, 5, 8, 9]),
])
def test_parse_selection(text, n, want):
    assert parse_selection(text, n) == want


@pytest.mark.parametrize("text", ["1-20", "0", "abc", "", "5-2"])
def test_parse_selection_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_selection(text, 14)


def test_new_keywords_skips_existing_and_repeats():
    fresh, skipped = new_keywords(["schools in Kalkaji"],
                                  ["Schools in Kalkaji", "schools in Saket", " schools in saket ", "schools in Hauz Khas"])
    assert fresh == ["schools in Saket", "schools in Hauz Khas"]
    assert skipped == ["Schools in Kalkaji", "schools in saket"]

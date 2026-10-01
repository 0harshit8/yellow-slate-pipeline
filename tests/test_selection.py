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


from stages.selection import parse_vols, suggest_schools


def school(name, vol, count=1):
    return {"name": name, "volume": vol, "count": str(count)}


def test_suggest_takes_100_plus_highest_first_max_12():
    schools = [school(f"S{i}", str(100 + i * 10)) for i in range(1, 16)]  # 15 schools, all 100+
    nums, topup = suggest_schools(schools)
    assert nums == list(range(15, 3, -1))  # top 12 by volume
    assert topup == set()


def test_suggest_tops_up_to_8_by_volume():
    vols = ["500", "90", "1,200", "40", "300", "0", "80", "70", "60", "10"]
    nums, topup = suggest_schools([school(f"S{i}", v) for i, v in enumerate(vols, 1)])
    assert nums[:3] == [3, 1, 5]  # the three at 100+
    assert len(nums) == 8
    assert topup == {2, 7, 8, 9, 4}


def test_suggest_tie_goes_to_higher_count():
    schools = [school("A", "200", 1), school("B", "200", 3)] + [school(f"S{i}", "150") for i in range(6)]
    nums, _ = suggest_schools(schools)
    assert nums[:2] == [2, 1]


def test_suggest_refuses_missing_volumes():
    with pytest.raises(ValueError, match="B"):
        suggest_schools([school("A", "200"), school("B", "")])


def test_parse_vols():
    assert parse_vols("1:320, 2:90, 5: 1,500, 7=0", 10) == {1: 320, 2: 90, 5: 1500, 7: 0}
    with pytest.raises(ValueError):
        parse_vols("11:50", 10)
    with pytest.raises(ValueError):
        parse_vols("nothing here", 10)

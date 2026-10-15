import os

from stages import write


def test_previous_output_moved_aside(tmp_path):
    folder = tmp_path / "output" / "best-schools-in-x-delhi"
    folder.mkdir(parents=True)
    (folder / "blog.md").write_text("old blog")
    moved = write.clear_previous(str(folder))
    assert not folder.exists() or not os.listdir(folder)
    assert open(os.path.join(moved, "blog.md")).read() == "old blog"
    assert os.path.dirname(moved) == str(tmp_path / "data" / "previous_runs")  # outside output/


def test_no_previous_output_is_a_noop(tmp_path):
    assert write.clear_previous(str(tmp_path / "missing")) is None


def test_pick_ratings_read_by_page_name(tmp_path):
    """The picker counts each school's directory ratings and writes them to pick.json, then
    nothing reads them. On the Kolar rebuild that threw away a 225-rating Justdial listing for
    Sri R.v. School and sent the researcher out blind, which spent 11 searches and reported
    'no review signal'. The count is keyed by the name the directory page used, which is the
    CMS tab's School column, not its CMS name.
    """
    import json
    folder = tmp_path / "best-schools-in-kolar"
    folder.mkdir(parents=True)
    (folder / "pick.json").write_text(json.dumps([
        {"name": "Sri R.v. School", "reviews": 225, "sources": ["https://justdial.com/kolar"]},
        {"name": "JSS Public School", "reviews": 0, "sources": []}]), encoding="utf-8")
    assert write.pick_ratings(str(folder)) == {"sri r v school": 225, "jss public school": 0}


def test_pick_ratings_missing_file_is_empty(tmp_path):
    assert write.pick_ratings(str(tmp_path / "nope")) == {}


def test_prompt_carries_the_directory_rating_count():
    schools = [{"name": "Sri R.v. School", "id": "23222", "slug": "sri-rv-school",
                "area": "New Extension", "page_name": "Sri R.v. School"},
               {"name": "JSS Public School", "id": "23228", "slug": "jss-public-school",
                "area": "Malur", "page_name": "JSS Public School"}]
    prompt = write.build_prompt("best schools in Kolar", "Kolar", "Kolar", "best-schools-in-kolar",
                                schools, ratings={"sri r v school": 225})
    assert "Directory ratings: 225" in prompt
    assert "Directory ratings: NONE" in prompt  # the one the picker saw no rating for


def test_pick_ratings_keeps_the_highest_for_a_repeated_name(tmp_path):
    """Kolar's shortlist carried Chinmaya Vidyalaya twice, Cottonpet with 210 ratings and
    PC Extn. with none. Keyed by name, the second overwrote the first and the school was sent
    out as unrated. stages/names.py merges duplicates with max() for the same reason."""
    import json
    folder = tmp_path / "b"
    folder.mkdir()
    (folder / "pick.json").write_text(json.dumps([
        {"name": "Chinmaya Vidyalaya", "reviews": 210},
        {"name": "Chinmaya Vidyalaya", "reviews": 0}]), encoding="utf-8")
    assert write.pick_ratings(str(folder)) == {"chinmaya vidyalaya": 210}

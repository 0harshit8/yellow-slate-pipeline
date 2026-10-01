import json
import os

from stages import assets


def test_graph_drawn_and_placeholders_swapped(tmp_path, monkeypatch):
    (tmp_path / "blog.md").write_text("## 1. A\n\n<!-- IMAGE: a -->\n\n### Parent Review\n\n<!-- GRAPH: a -->\n\n<!-- IMAGE: ghost -->\n")
    (tmp_path / "assets.json").write_text(json.dumps({"schools": [
        {"name": "A", "slug": "a", "image_url": None, "reviews": {"Academics": [80, 10], "Fees": [55, 30]}}]}))
    problems = assets.process(str(tmp_path))
    md = (tmp_path / "blog.md").read_text()
    assert "![Parent sentiment breakdown for A](graphs/a.png)" in md
    assert "<!--" not in md  # unknown and image-less placeholders are removed
    assert os.path.exists(tmp_path / "graphs" / "a.png")
    assert any("no official image" in p for p in problems)
    assert "Pipeline: images and graphs" in (tmp_path / "notes.md").read_text()


def test_bad_review_data_gives_no_graph(tmp_path):
    (tmp_path / "blog.md").write_text("<!-- GRAPH: a -->\n")
    (tmp_path / "assets.json").write_text(json.dumps({"schools": [
        {"name": "A", "slug": "a", "image_url": None, "reviews": {"Academics": "lots"}}]}))
    problems = assets.process(str(tmp_path))
    assert any("no category review percentages" in p for p in problems)
    assert "<!--" not in (tmp_path / "blog.md").read_text()

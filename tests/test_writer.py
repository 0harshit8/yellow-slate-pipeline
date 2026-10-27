from types import SimpleNamespace

import config
import pipeline

BLOGS = [
    {"Writer": "Sister", "Keyword": "schools in a", "Status": "new"},
    {"Writer": "Harshit", "Keyword": "schools in b", "Status": "new"},
    {"Writer": "", "Keyword": "schools in c", "Status": "new"},
]
ARGS = SimpleNamespace(row=[], limit=0)


def test_no_writer_sees_every_row(monkeypatch):
    monkeypatch.setattr(config, "WRITER", "")
    assert len(pipeline.rows_in(BLOGS, "new", ARGS)) == 3


def test_writer_only_gets_own_rows(monkeypatch):
    monkeypatch.setattr(config, "WRITER", "sister")
    assert [b["Keyword"] for b in pipeline.rows_in(BLOGS, "new", ARGS)] == ["schools in a"]


def test_writer_cannot_take_someone_elses_row_by_name(monkeypatch):
    monkeypatch.setattr(config, "WRITER", "Sister")
    args = SimpleNamespace(row=["schools in b"], limit=0)
    assert pipeline.rows_in(BLOGS, "new", args) == []

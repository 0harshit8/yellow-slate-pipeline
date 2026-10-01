import os

from stages import write


def test_previous_output_moved_aside(tmp_path):
    folder = tmp_path / "output" / "best-schools-in-x-delhi"
    folder.mkdir(parents=True)
    (folder / "blog.md").write_text("old blog")
    moved = write.clear_previous(str(folder))
    assert not folder.exists() or not os.listdir(folder)
    assert open(os.path.join(moved, "blog.md")).read() == "old blog"
    assert os.path.basename(os.path.dirname(moved)) == "_previous"


def test_no_previous_output_is_a_noop(tmp_path):
    assert write.clear_previous(str(tmp_path / "missing")) is None

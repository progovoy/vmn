"""A change's function under git's default funcname, which names the nearest
old-file line above it that starts with a letter, ``_`` or ``$`` -- not only a
definition: module code after a function (an ``if __name__`` block, constants,
a text file's prose) and a removed column-0 line name the changes below them in
a 3-line-context patch as they do in a ``-U0`` one (``import-mlflow --repo``),
and a line past a hunk's ``@@`` counts (format-patch's ``-- `` signature) is no
change of it."""
import time

from test_features_change_scope import (  # noqa: F401
    _both,
    _commit,
    _edit,
    _symbols,
    repo,
)

TOP = "def top():\n" + "".join(f"    v{i} = {i}\n" for i in range(8)) + "\n\n"


def test_an_edit_in_a_main_block_after_a_function_names_the_block(repo):  # noqa: F811
    _commit(repo, {"train.py": "def train():\n    return 1\n\n\n"
                               "if __name__ == \"__main__\":\n    x = 1\n    train()\n"})
    _edit(repo, "train.py", "    train()\n", "    train() * 2\n")
    diff, symbols, unified0 = _both(repo, "train.py")
    assert "@@ def train():" in diff
    assert symbols == ['train.py::if __name__ == "__main__":'] == unified0


def test_an_edit_in_module_constants_after_a_function_names_the_line_above_it(repo):  # noqa: F811
    _commit(repo, {"cfg.py": "def helper():\n    return 1\n\n\nBATCH = 32\nLR = [\n    0.1,\n]\n"})
    _edit(repo, "cfg.py", "    0.1,\n", "    0.2,\n")
    diff, symbols, unified0 = _both(repo, "cfg.py")
    assert "@@ def helper():" in diff
    assert symbols == ["cfg.py::LR = ["] == unified0


def test_a_removed_column_0_line_names_the_next_change_of_its_hunk(repo):  # noqa: F811
    _commit(repo, {"cfg.py": TOP + "LR = dict(\n    a=1,\n    b=2,\n)\n"})
    _edit(repo, "cfg.py", "LR = dict(\n    a=1,\n    b=2,", "LR = dict(  # x\n    a=1,\n    b=3,")
    diff, symbols, unified0 = _both(repo, "cfg.py")
    assert diff.count("\n@@ ") == 1 and "@@ def top():" in diff
    assert symbols == ["cfg.py::top", "cfg.py::LR = dict("] == unified0


def test_a_text_files_prose_line_names_the_change_below_it(repo):  # noqa: F811
    lines = "".join(f"  l{i}\n" for i in range(8))
    _commit(repo, {"R.md": f"Title\n{lines}Intro\n  more\n  text\n  here\n"})
    _edit(repo, "R.md", "  text\n", "  TEXT\n")
    diff, symbols, unified0 = _both(repo, "R.md")
    assert "@@ Title" in diff
    assert symbols == ["R.md::Intro"] == unified0


def test_a_long_column_0_context_line_is_cut_as_git_cuts_a_funcname_and_read_quickly(repo):  # noqa: F811
    long_line = "func" + " " * 30000 + "-"
    _commit(repo, {"x.go": f"func main() {{\n\trun()\n}}\n\n{long_line}\n\ta := 1\n\tb := 2\n"})
    _edit(repo, "x.go", "b := 2", "b := 3")
    started = time.monotonic()
    diff, symbols, unified0 = _both(repo, "x.go")
    assert time.monotonic() - started < 1.0
    assert "@@ func main() {" in diff
    assert symbols == ["x.go::func"] == unified0


def test_a_format_patch_signature_after_a_definition_in_trailing_context_names_nothing(repo):  # noqa: F811
    _, git = repo
    _commit(repo, {"m.py": "import os\n\n\ndef load_data(path):\n    with open(path) as f:\n"
                           "        return f.read()\n\n\ndef train_step(model):\n    return model\n"})
    git("tag", "base")
    _edit(repo, "m.py", "f.read()", "f.read().strip()")
    git("commit", "-qam", "strip")
    mbox = git("format-patch", "--stdout", "base..HEAD")
    assert " def train_step(model):\n-- \n" in mbox
    assert _symbols(mbox) == ["m.py::load_data"] == _symbols(git("diff", "-U0", "base", "HEAD"))

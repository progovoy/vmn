"""A hunk whose header names nothing -- it starts at the top of the file, or
only lines git's default funcname skips (blank, indented, comments,
``#include``) are above it -- takes its change's function from its own column-0
context lines, and such a line names what git prints for it as a funcname: its
first 80 bytes, up to its first byte that is not UTF-8. So a 3-line-context
patch (capture: GitPython decodes with ``surrogateescape``; the backfill with
``replace``) names what a ``-U0`` one (``import-mlflow --repo``) does."""
import os
import subprocess

import pytest
from vmn_exp.core.features import features_from_patches

MODEL = """\
def load_data(path):
    with open(path) as f:
        return f.read()


def train_step(model, batch, lr=0.1):
    loss = model(batch)
    loss.backward()
    return loss
"""
TOP = "def top():\n" + "".join(f"    v{i} = {i}\n" for i in range(8)) + "\n\n"


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               HOME=str(tmp_path), GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@x.io",
               GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@x.io")

    def git(*args):
        return subprocess.run(["git", *args], cwd=path, env=env, check=True,
                              capture_output=True).stdout

    git("init", "-q", "-b", "main")
    return path, git


def _commit(repo, files):
    path, git = repo
    for name, content in files.items():
        (path / name).write_bytes(content if isinstance(content, bytes) else content.encode())
    git("add", "-A")
    git("commit", "-qm", "base")


def _edit(repo, name, old, new):
    path = repo[0] / name
    data = path.read_bytes()
    assert old.encode() in data
    path.write_bytes(data.replace(old.encode(), new.encode()))


def _symbols(data, errors="replace"):
    return features_from_patches([data.decode("utf-8", errors)])["changed"]["symbols"]


def _both(repo, name, errors="replace"):
    """The -U3 diff, its symbols (decoded with *errors*) and those of the -U0
    diff of the same edit (decoded as ``import-mlflow --repo`` does)."""
    git = repo[1]
    diff = git("diff", "HEAD", "--", name)
    unified0 = git("diff", "-U0", "HEAD", "--", name)
    return diff.decode("utf-8", "replace"), _symbols(diff, errors), _symbols(unified0)


def test_an_edit_in_the_function_a_file_starts_with_names_it(repo):
    _commit(repo, {"model.py": MODEL})
    _edit(repo, "model.py", "        return f.read()\n", "        return f.read().strip()\n")
    diff, symbols, unified0 = _both(repo, "model.py")
    assert " @@\n def load_data(path):\n" in diff
    assert symbols == ["model.py::load_data"] == unified0


def test_a_commit_editing_a_files_first_function_names_it_in_its_format_patch(repo):
    _, git = repo
    _commit(repo, {"model.py": MODEL})
    git("tag", "base")
    _edit(repo, "model.py", "open(path)", "open(path, encoding='utf-8')")
    git("commit", "-qam", "read utf-8")
    mbox = git("format-patch", "--stdout", "base..HEAD")
    assert b" @@\n def load_data(path):\n" in mbox
    assert _symbols(mbox) == ["model.py::load_data"] == _symbols(git("diff", "-U0", "base", "HEAD"))


@pytest.mark.parametrize("name, text, old, new, symbol", [
    ("train.py", "# Train a model.\n# Usage: python train.py\n\n\ndef train(x):\n"
                 "    y = x + 1\n    return y\n", "x + 1", "x + 2", "train"),
    ("app.js", "/*\n * Copyright 2026 A.\n */\n\nfunction load(path) {\n"
               "  return read(path);\n}\n", "read(path)", "read(path, 'utf8')", "load"),
    ("main.c", "#include <stdio.h>\n#include <stdlib.h>\n\nint main(void)\n{\n"
               "    printf(\"hi\\n\");\n    return 0;\n}\n", "\"hi", "\"hello", "main"),
], ids=["python-comments", "js-comment-block", "c-includes"])
def test_an_edit_in_a_function_with_only_comments_above_it_names_it(
    repo, name, text, old, new, symbol,
):
    _commit(repo, {name: text})
    _edit(repo, name, old, new)
    diff, symbols, unified0 = _both(repo, name)
    assert [line for line in diff.splitlines() if line.startswith("@@ ")][0].endswith(" @@")
    assert symbols == [f"{name}::{symbol}"] == unified0


@pytest.mark.parametrize("line", [
    'MESSAGE = ("Модель_для_классификации_изображений_с_вниманием",',
    'TITLE = ("画像分類モデル：注意機構付きの畳み込みネットワーク",',
], ids=["cyrillic", "japanese"])
def test_a_column_0_line_over_80_bytes_names_its_first_80_bytes_as_git_does(repo, line):
    assert len(line) < 80 < len(line.encode())
    _commit(repo, {"msg.py": f"{TOP}{line}\n    \"b\",\n    \"c\",\n)\n"})
    _edit(repo, "msg.py", '"c",', '"C",')
    diff, symbols, unified0 = _both(repo, "msg.py")
    assert "@@ def top():" in diff
    cut = line.encode()[:80].decode("utf-8", "ignore")  # git keeps whole characters only
    assert len(cut.encode()) < 80
    assert symbols == [f"msg.py::{cut}"] == unified0


@pytest.mark.parametrize("errors", ["surrogateescape", "replace"], ids=["capture", "backfill"])
def test_a_column_0_line_with_bytes_that_are_not_utf8_names_what_comes_before_them(
    repo, errors,
):
    _commit(repo, {"menu.py": TOP.encode() + b"TITLE = ('caf\xe9 cr\xe8me',\n    'b',\n"
                                              b"    'c',\n)\n"})
    _edit(repo, "menu.py", "'c',", "'C',")
    diff, symbols, unified0 = _both(repo, "menu.py", errors)
    assert "@@ def top():" in diff
    assert symbols == ["menu.py::TITLE = ('caf"] == unified0

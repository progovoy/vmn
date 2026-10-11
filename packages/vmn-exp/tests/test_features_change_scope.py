"""The function a change is in, from git's default 3-line-context patches (what
capture and the backfill parse): a hunk header names the function *above* the
hunk's leading context, so a column-0 definition in that context is the change's
scope — the name a ``-U0`` diff (``import-mlflow --repo``) gives the same edit
under git's default funcname, which skips methods and nested defs."""
import os
import subprocess

import pytest
from vmn_exp.core.features import features_from_patches

MODEL = """\
import os


def load_data(path):
    with open(path) as f:
        return f.read()


def train_step(model, batch, lr=0.1):
    loss = model(batch)
    loss.backward()
    return loss
"""
APP = """\
const a = 1;

function load(path) {
  return read(path);
}

function train(model, batch) {
  const loss = model(batch);
  return loss;
}
"""


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               HOME=str(tmp_path), GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@x.io",
               GIT_COMMITTER_NAME="A", GIT_COMMITTER_EMAIL="a@x.io")

    def git(*args):
        return subprocess.run(["git", *args], cwd=path, env=env, check=True,
                              capture_output=True, text=True).stdout

    git("init", "-q", "-b", "main")
    return path, git


def _commit(repo, files):
    path, git = repo
    for name, text in files.items():
        (path / name).write_text(text)
    git("add", "-A")
    git("commit", "-qm", "base")


def _edit(repo, name, old, new):
    path, _ = repo
    text = (path / name).read_text()
    assert old in text
    (path / name).write_text(text.replace(old, new))


def _symbols(text, prefix=""):
    return features_from_patches([(prefix, text)])["changed"]["symbols"]


def _both(repo, *paths):
    """The symbols of the -U3 diff and of the -U0 diff of the same edit."""
    _, git = repo
    diff = git("diff", "HEAD", "--", *paths)
    return diff, _symbols(diff), _symbols(git("diff", "-U0", "HEAD", "--", *paths))


@pytest.mark.parametrize("attributes", [None, "*.py diff=python\n"],
                         ids=["default-driver", "python-driver"])
def test_an_edit_at_the_top_of_a_short_second_function_names_that_function(
    repo, attributes,
):
    _commit(repo, dict({"model.py": MODEL},
                       **({".gitattributes": attributes} if attributes else {})))
    _edit(repo, "model.py", "    loss = model(batch)\n", "    loss = model(batch) * 2\n")
    diff, symbols, unified0 = _both(repo, "model.py")
    assert "@@ def load_data(path):" in diff
    assert symbols == ["model.py::train_step"] == unified0


def test_an_edit_in_a_files_first_function_names_it_and_not_the_next_one(repo):
    _commit(repo, {"model.py": MODEL})
    _edit(repo, "model.py", "        return f.read()\n", "        return f.read().strip()\n")
    diff, symbols, unified0 = _both(repo, "model.py")
    assert "@@ import os" in diff and " def train_step(" in diff
    assert symbols == ["model.py::load_data"] == unified0


def test_each_change_run_of_one_hunk_names_its_own_function(repo):
    _commit(repo, {"model.py": MODEL})
    _edit(repo, "model.py", "        return f.read()\n", "        return f.read().strip()\n")
    _edit(repo, "model.py", "    loss = model(batch)\n", "    loss = model(batch) * 2\n")
    diff, symbols, unified0 = _both(repo, "model.py")
    assert diff.count("\n@@ ") == 1
    assert symbols == ["model.py::load_data", "model.py::train_step"] == unified0


def test_a_javascript_edit_names_the_function_it_is_in(repo):
    _commit(repo, {"app.js": APP})
    _edit(repo, "app.js", "model(batch);", "model(batch) * 2;")
    diff, symbols, unified0 = _both(repo, "app.js")
    assert "@@ function load(path) {" in diff
    assert symbols == ["app.js::train"] == unified0


def test_a_dep_files_edit_names_the_dep_function_it_is_in(repo):
    _commit(repo, {"lib.py": "def helper():\n    return 1\n\n\ndef other(x):\n"
                             "    y = x + 1\n    return y\n"})
    _edit(repo, "lib.py", "x + 1", "x + 2")
    diff, _, _ = _both(repo, "lib.py")
    assert "@@ def helper():" in diff
    assert _symbols(diff, prefix="../dep") == ["../dep/lib.py::other"]


NET = """\
import torch


class Net(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.fc = torch.nn.Linear(4, 4)

    def forward(self, x):
        h = self.fc(x)
        h = torch.relu(h)
        h = self.fc(h)
        h = torch.relu(h)
        h = self.fc(h)
        return h


def train(model):
    def evaluate():
        return model.eval()
    for epoch in range(10):
        lr = 0.1
    return lr
"""
TRAINER = """\
class Trainer {
  constructor(m) {
    this.m = m;
  }

  step(batch) {
    const loss = this.m(batch);
    let a = 1;
    let b = 2;
    let c = 3;
    return loss;
  }
}
"""


def _edit_symbols(repo, name, old, new):
    """The -U3 diff and the -U3 / -U0 symbols of one edit, then the edit undone."""
    _edit(repo, name, old, new)
    found = _both(repo, name)
    repo[1]("checkout", "--", name)
    return found


def test_a_methods_edits_near_its_def_and_deep_in_it_name_what_the_default_driver_does(repo):
    _commit(repo, {"net.py": NET})
    near_diff, near, near0 = _edit_symbols(repo, "net.py", "self.fc(x)\n", "self.fc(x) * 2\n")
    _, deep, deep0 = _edit_symbols(repo, "net.py", "        return h\n", "        return h * 2\n")
    assert "\n     def forward(self, x):\n" in near_diff
    assert near == deep == near0 == deep0 == ["net.py::Net"]


def test_an_edit_after_a_nested_def_names_the_outer_function(repo):
    _commit(repo, {"net.py": NET})
    _edit(repo, "net.py", "lr = 0.1", "lr = 0.2")
    diff, symbols, unified0 = _both(repo, "net.py")
    assert "\n     def evaluate():\n" in diff
    assert symbols == ["net.py::train"] == unified0


def test_a_javascript_method_edit_near_its_def_names_its_class_as_git_does(repo):
    _commit(repo, {"trainer.js": TRAINER})
    _edit(repo, "trainer.js", "this.m(batch);", "this.m(batch) * 2;")
    diff, symbols, unified0 = _both(repo, "trainer.js")
    assert "\n   step(batch) {\n" in diff
    assert symbols == ["trainer.js::Trainer"] == unified0

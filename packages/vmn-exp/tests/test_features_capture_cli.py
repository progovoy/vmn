"""``vmn-exp create``/``run`` write a ``features`` entry right after the create
entry: the files, functions and commit subjects of the run's own change, the
repo's untracked paths, and who ran it (git config in the repo, else
``VMN_EXP_AUTHOR``, else the first local commit's ``From:``). Capturing is
best-effort: a failure is a warning and the run is created without it."""
import os

import pytest
from exp_helpers import _PY, _bootstrap, _exp, _storage
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.fold import fold_features, fold_log

TRAIN = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    vmn_logging.ensure_logger()
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)


def _write(app_layout, name, content):
    with open(os.path.join(app_layout.repo_path, name), "w") as f:
        f.write(content)


def _dirty_tree(app_layout):
    """train.py edited inside train_step, loss.py in a local commit, notes.md untracked."""
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    app_layout.write_file_commit_and_push(
        "test_repo_0", "loss.py", "def focal_loss():\n    pass\n",
        push=False, commit_msg="try focal loss",
    )
    _write(app_layout, "train.py", TRAIN.format("b"))
    _write(app_layout, "notes.md", "idea\n")


def _runs(app_layout):
    return set(_storage(app_layout).list_record_names(app_layout.app_name))


def _new_run(app_layout, **kwargs):
    before = _runs(app_layout)
    assert _exp(app_layout.app_name, **kwargs) == 0
    (verstr,) = _runs(app_layout) - before
    return verstr


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def _features(app_layout, verstr):
    return fold_features(fold_log(_log(app_layout, verstr)))


def test_create_writes_the_features_entry_right_after_the_create_entry(app_layout):
    _dirty_tree(app_layout)
    verstr = _new_run(app_layout)

    log = _log(app_layout, verstr)
    assert [e["type"] for e in log[:2]] == ["create", "features"]
    entry = log[1]
    assert entry["features_version"] == FEATURES_VERSION
    assert entry["source"] == "capture"
    assert sorted(entry["changed"]["files"]) == ["loss.py", "train.py"]
    # train_step from the hunk context; focal_loss defined on the new file's added lines
    assert sorted(entry["changed"]["symbols"]) == ["loss.py::focal_loss", "train.py::train_step"]
    assert entry["changed"]["untracked"] == ["notes.md"]
    assert entry["commits"] == ["try focal loss"]


def test_the_author_is_the_repo_git_config_email(app_layout):
    _dirty_tree(app_layout)
    author = _features(app_layout, _new_run(app_layout))["author"]
    assert author["git_user_email"] == "test@test.com"
    assert author["source"] == "git"
    assert author["writer"]


def test_without_a_git_email_vmn_exp_author_names_the_author(app_layout, monkeypatch):
    _dirty_tree(app_layout)
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")
    monkeypatch.setenv("VMN_EXP_AUTHOR", "bob@x.io")
    author = _features(app_layout, _new_run(app_layout))["author"]
    assert (author["git_user_email"], author["source"]) == ("bob@x.io", "env")


def test_without_a_git_email_or_env_the_first_local_commit_names_the_author(
    app_layout, monkeypatch,
):
    _dirty_tree(app_layout)
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")
    author = _features(app_layout, _new_run(app_layout))["author"]
    assert (author["git_user_email"], author["source"]) == ("test@test.com", "commit")


def test_a_clean_tree_run_records_its_author_and_no_changes(app_layout):
    _bootstrap(app_layout)
    features = _features(app_layout, _new_run(app_layout))
    assert features["author"]["git_user_email"] == "test@test.com"
    assert "changed" not in features and "commits" not in features


def test_exp_run_writes_the_features_entry(app_layout):
    _dirty_tree(app_layout)
    verstr = _new_run(app_layout, action="run", run_cmd=[_PY, "-c", "pass"])
    features = _features(app_layout, verstr)
    assert features["source"] == "capture"
    assert "train.py" in features["changed"]["files"]


def test_a_capture_failure_warns_and_the_run_is_created_without_features(
    app_layout, monkeypatch, capfd,
):
    import vmn_exp.gitmode.features as gitmode_features

    def _boom(texts):
        raise RuntimeError("parser exploded")

    _dirty_tree(app_layout)
    monkeypatch.setattr(gitmode_features, "features_from_patches", _boom)
    capfd.readouterr()
    verstr = _new_run(app_layout)

    assert [e["type"] for e in _log(app_layout, verstr)] == ["create"]
    assert "features" in capfd.readouterr().err

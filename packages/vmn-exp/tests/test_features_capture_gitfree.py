"""Features of git-free runs (``create_from_snapshot``): ``vmn-exp export``
records who exported (``exported_by`` in ``vmn_experiment.yml``); a run created
from the exported tree copies the exported run's code facts (``source:
export``) and names this host's author — git config, else the exporter's
email, else ``VMN_EXP_AUTHOR``. Without the exported run's entry only the
author is known, at version 0, below every real one, so the backfill derives
the rest."""
import logging
import os
import subprocess

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, extract_dev_verstr
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity
from vmn_exp.core import writer as experiment_writer
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.core.from_snapshot import create_from_snapshot
from vmn_exp.snapshot import open_storage

TRAIN = "def train_step():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return {}\n"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    vmn_logging.ensure_logger()
    monkeypatch.delenv(identity.AUTHOR_ENV, raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)
    monkeypatch.setenv("VMN_WRITER_ID", "pod-1")
    experiment_writer._WRITER_ID = None


def _no_git_email(monkeypatch):
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")


def _exported(app_layout, capfd, tmp_path):
    """Export a run of a train_step edit; returns (run verstr, export dir)."""
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", TRAIN.format("a"))
    with open(os.path.join(app_layout.repo_path, "train.py"), "w") as f:
        f.write(TRAIN.format("b"))
    capfd.readouterr()
    assert _exp(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    out = str(tmp_path / "export")
    assert _exp(app_layout.app_name, action="export", version=verstr, output=out) == 0
    return verstr, out


def _git_free_run(tree, tmp_path, meta_path=None):
    storage = open_storage(root=str(tmp_path / "pod-store"), area="runs")
    verstr, err = create_from_snapshot(storage, None, meta_path or tree)
    assert err is None
    app = yaml.safe_load(open(os.path.join(tree, "vmn_metadata.yml")))["app_name"]
    return storage.load_merged_log(app, verstr)


def _hand_made_tree(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "vmn_metadata.yml").write_text(
        "verstr: 0.0.1-dev.abc1234.def5678\napp_name: testapp\n"
        "base_version: 0.0.1\nbase_commit: abc1234\nbranch: master\n"
    )
    return str(tree)


def test_export_records_who_exported(app_layout, capfd, tmp_path):
    _, out = _exported(app_layout, capfd, tmp_path)
    with open(os.path.join(out, "vmn_experiment.yml")) as f:
        exported_by = yaml.safe_load(f)["exported_by"]
    assert exported_by["git_user_email"] == "test@test.com"
    assert exported_by["writer"] == "pod-1"


def test_a_git_free_run_copies_the_exported_runs_code_facts(
    app_layout, capfd, tmp_path, monkeypatch,
):
    _, out = _exported(app_layout, capfd, tmp_path)
    _no_git_email(monkeypatch)
    log = _git_free_run(out, tmp_path)

    assert [e["type"] for e in log] == ["create", "features"]
    entry = log[1]
    assert entry["source"] == "export"
    assert entry["features_version"] == FEATURES_VERSION
    assert entry["changed"]["files"] == ["train.py"]
    assert entry["changed"]["symbols"] == ["train.py::train_step"]
    assert entry["author"]["git_user_email"] == "test@test.com"
    assert entry["author"]["source"] == "export"
    assert entry["author"]["writer"] == "pod-1"


def test_the_metadata_file_path_finds_the_exported_run_too(app_layout, capfd, tmp_path):
    _, out = _exported(app_layout, capfd, tmp_path)
    log = _git_free_run(out, tmp_path, meta_path=os.path.join(out, "vmn_metadata.yml"))
    assert fold_features(fold_log(log))["changed"]["files"] == ["train.py"]


def test_git_config_in_the_tree_names_the_author_before_the_exporter(
    app_layout, capfd, tmp_path,
):
    _, out = _exported(app_layout, capfd, tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=out, check=True)
    subprocess.run(["git", "config", "user.email", "pod@x.io"], cwd=out, check=True)
    author = fold_features(fold_log(_git_free_run(out, tmp_path)))["author"]
    assert (author["git_user_email"], author["source"]) == ("pod@x.io", "git")


def test_without_the_exported_run_only_the_author_is_recorded_at_version_0(
    tmp_path, monkeypatch,
):
    _no_git_email(monkeypatch)
    monkeypatch.setenv("VMN_EXP_AUTHOR", "carol@x.io")
    log = _git_free_run(_hand_made_tree(tmp_path), tmp_path)

    entry = log[1]
    assert entry["type"] == "features" and entry["source"] == "export"
    assert entry["features_version"] == 0
    assert "changed" not in entry and "commits" not in entry
    assert entry["author"]["git_user_email"] == "carol@x.io"
    assert entry["author"]["source"] == "env"


def test_an_unreadable_exported_run_still_creates_the_run(tmp_path, caplog):
    tree = _hand_made_tree(tmp_path)
    with open(os.path.join(tree, "vmn_experiment.yml"), "w") as f:
        f.write("log: [unclosed\n")
    log = _git_free_run(tree, tmp_path)
    assert [e["type"] for e in log] == ["create"]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("features" in message for message in warnings)

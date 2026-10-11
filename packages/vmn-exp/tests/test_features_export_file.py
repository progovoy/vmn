"""A git-free run's features come from ``vmn_features.yml``, the small file
``vmn-exp export`` writes next to ``vmn_metadata.yml`` (the exported run's
folded features and ``exported_by``) — never from the exported run's whole
log in ``vmn_experiment.yml``, which holds every metrics entry. An older
export without the file is read from its log only while that file is small;
``start_run()`` reads it before taking the shared ``VMN_EXPERIMENT_DIR`` lock."""
import contextlib
import os

import yaml
from exp_helpers import _storage
from test_features_capture_gitfree import (  # noqa: F401
    _env,
    _exported,
    _git_free_run,
    _hand_made_tree,
    _no_git_email,
)
from vmn_exp.core import from_snapshot, identity, snapshot_features
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.sdk import create as sdk_create
from vmn_exp.sdk import start_run
from vmn_exp.snapshot import open_storage


def test_export_writes_the_runs_features_to_a_file_of_their_own(app_layout, capfd, tmp_path):
    _, out = _exported(app_layout, capfd, tmp_path)

    with open(os.path.join(out, "vmn_features.yml")) as f:
        written = yaml.safe_load(f)

    storage = _storage(app_layout)
    [verstr] = storage.list_record_names(app_layout.app_name)
    log = storage.load_merged_log(app_layout.app_name, verstr)
    assert written["features"] == fold_features(fold_log(log))
    assert written["features"]["changed"]["files"] == ["train.py"]
    assert written["exported_by"]["git_user_email"] == "test@test.com"


def test_a_git_free_run_never_parses_the_exported_log(
    app_layout, capfd, tmp_path, monkeypatch,
):
    _, out = _exported(app_layout, capfd, tmp_path)
    _no_git_email(monkeypatch)
    with open(os.path.join(out, "vmn_experiment.yml"), "w") as f:
        f.write("log: [unclosed\n")

    entry = _git_free_run(out, tmp_path)[1]

    assert entry["source"] == "export"
    assert entry["features_version"] == FEATURES_VERSION
    assert entry["changed"]["files"] == ["train.py"]
    assert entry["author"]["git_user_email"] == "test@test.com"
    assert entry["author"]["source"] == "export"


def _older_export(tmp_path, metrics_entries=0):
    """A tree an older vmn-exp exported: no ``vmn_features.yml``, the run's
    features entry in ``vmn_experiment.yml``'s log among its metrics."""
    tree = _hand_made_tree(tmp_path)
    log = [{"type": "create", "timestamp": "2026-01-01T00:00:00Z"},
           {"type": "features", "features_version": FEATURES_VERSION, "source": "capture",
            "changed": {"files": ["train.py"]}}]
    log += [{"type": "metrics", "step": i, "metrics": {"loss": 0.5}}
            for i in range(metrics_entries)]
    with open(os.path.join(tree, "vmn_experiment.yml"), "w") as f:
        yaml.dump({"metadata": {}, "log": log, "exported_by": {"git_user_email": "old@x.io"}}, f)
    return tree


def test_an_older_exports_features_are_read_from_its_log_while_it_is_small(
    tmp_path, monkeypatch,
):
    _no_git_email(monkeypatch)
    entry = _git_free_run(_older_export(tmp_path), tmp_path)[1]
    assert entry["features_version"] == FEATURES_VERSION
    assert entry["changed"]["files"] == ["train.py"]
    assert entry["author"]["git_user_email"] == "old@x.io"


def test_an_older_export_too_large_to_read_names_only_the_author(tmp_path, monkeypatch):
    _no_git_email(monkeypatch)
    monkeypatch.setenv(identity.AUTHOR_ENV, "carol@x.io")
    tree = _older_export(tmp_path, metrics_entries=200)
    monkeypatch.setattr(snapshot_features, "LEGACY_READ_MAX_BYTES", 2000)
    assert os.path.getsize(os.path.join(tree, "vmn_experiment.yml")) > 2000

    entry = _git_free_run(tree, tmp_path)[1]

    assert entry["features_version"] == 0
    assert "changed" not in entry
    assert entry["author"]["git_user_email"] == "carol@x.io"
    assert entry["author"]["source"] == "env"


def test_start_run_reads_the_exports_features_before_taking_the_shared_dir_lock(
    app_layout, capfd, tmp_path, monkeypatch,
):
    _, out = _exported(app_layout, capfd, tmp_path)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", out)
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(tmp_path / "shared"))
    held, reads = [], []
    real_lock, real_read = sdk_create.get_repo_lock, snapshot_features.export_features

    @contextlib.contextmanager
    def lock(root):
        with real_lock(root):
            held.append(root)
            try:
                yield
            finally:
                held.pop()

    def read(tree_dir):
        reads.append(bool(held))
        return real_read(tree_dir)

    monkeypatch.setattr(sdk_create, "get_repo_lock", lock)
    monkeypatch.setattr(from_snapshot, "export_features", read)
    monkeypatch.setattr(sdk_create, "export_features", read, raising=False)
    storage = open_storage(root=str(tmp_path / "pod-store"), area="runs")

    with start_run(app_layout.app_name, storage=storage, system_metrics=False,
                   capture_env=False) as run:
        verstr = run.id

    assert reads == [False]
    features = fold_features(fold_log(storage.load_merged_log(app_layout.app_name, verstr)))
    assert features["source"] == "export"
    assert features["changed"]["files"] == ["train.py"]

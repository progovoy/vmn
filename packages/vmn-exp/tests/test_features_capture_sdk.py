"""The SDK's git mode (``start_run`` in a checkout) records a run's features
like the CLI; a fork records its own and inherits neither its source's
features nor its intent; ``features_for_working_tree`` reads the tree's
features without creating a run."""
import os

import pytest
from exp_helpers import _bootstrap, _storage
from vmn_exp.core import identity
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.fold import fold_features, fold_intent, fold_log
from vmn_exp.core.writer import create_log_entry
from vmn_exp.gitmode.coldstart import build_vcs
from vmn_exp.gitmode.features import features_for_working_tree
from vmn_exp.sdk import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_RESUME_RUN_ID",
                identity.AUTHOR_ENV):
        monkeypatch.delenv(key, raising=False)


def _edit(app_layout):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "data.py", "rows = 1\n")
    with open(os.path.join(app_layout.repo_path, "data.py"), "w") as f:
        f.write("rows = 2\n")


def _log(app_layout, verstr):
    return _storage(app_layout).load_merged_log(app_layout.app_name, verstr)


def test_start_run_in_a_checkout_records_the_features_entry(app_layout):
    _edit(app_layout)
    with start_run(app_layout.app_name) as run:
        verstr = run.id

    features = fold_features(fold_log(_log(app_layout, verstr)))
    assert features["source"] == "capture"
    assert features["features_version"] == FEATURES_VERSION
    assert features["changed"]["files"] == ["data.py"]
    assert features["author"]["git_user_email"] == "test@test.com"


def test_a_fork_records_its_own_features_and_inherits_no_features_or_intent(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as source_run:
        source = source_run.id
    storage = _storage(app_layout)
    storage.append_log_entries(app_layout.app_name, source, "elsewhere", [
        create_log_entry("features", features_version=FEATURES_VERSION,
                         source="backfill", commits=["the source's commit"]),
        create_log_entry("intent", text="the source's intent", source="user"),
    ])

    with start_run(app_layout.app_name, fork_from=source) as fork:
        forked = fork.id

    log = _log(app_layout, forked)
    assert not [e for e in log if e.get("type") == "intent"]
    assert [e["source"] for e in log if e.get("type") == "features"] == ["capture"]
    fold = fold_log(log)
    assert "commits" not in fold_features(fold)
    assert fold_intent(fold) is None


def test_features_for_working_tree_reads_the_tree_without_creating_a_run(app_layout):
    _edit(app_layout)
    runs = _storage(app_layout).list_record_names(app_layout.app_name)

    features = features_for_working_tree(build_vcs(app_layout.app_name))

    assert "type" not in features
    assert features["source"] == "capture"
    assert features["changed"]["files"] == ["data.py"]
    assert "author" not in features
    assert _storage(app_layout).list_record_names(app_layout.app_name) == runs


def test_features_for_working_tree_is_empty_when_the_app_is_not_stamped(app_layout):
    assert features_for_working_tree(build_vcs(app_layout.app_name)) == {}

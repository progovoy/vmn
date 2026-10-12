"""A run's dep paths — the keys of its ``dep_base_commits`` and
``changesets`` but the repo itself (``.``) — name its stored code object's
deps (kept under safe names) for a rerun's features and for the backfill
alike: a record from before ``dep_base_commits`` names its deps by its
changesets alone."""
import types

import pytest
from vmn_exp.core import identity
from vmn_exp.core.code_patches import run_dep_paths
from vmn_exp.gitmode.features import rerun_features

DEP_DIFF = (
    "diff --git a/util.py b/util.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/util.py\n"
    "+++ b/util.py\n"
    "@@ -1 +1 @@\n"
    "-a = 1\n"
    "+a = 2\n"
)


@pytest.fixture
def vcs(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "a@x.io")
    return types.SimpleNamespace(backend=types.SimpleNamespace(repo_path=str(tmp_path)))


def test_dep_paths_join_base_commits_and_changesets_without_the_repo_itself():
    metadata = {
        "dep_base_commits": {"../libs/a": "abc1234"},
        "changesets": {".": {"hash": "1"}, "../libs/b": {"hash": "2"},
                       "../libs/a": {"hash": "3"}},
    }
    assert run_dep_paths(metadata) == ["../libs/a", "../libs/b"]


def test_a_run_without_deps_has_no_dep_paths():
    assert run_dep_paths({}) == []
    assert run_dep_paths({"changesets": {".": {"hash": "1"}}}) == []


def test_a_rerun_of_a_record_from_before_dep_base_commits_names_deps_by_changeset(vcs):
    metadata = {"changesets": {".": {"hash": "1"}, "../libs/dep": {"hash": "2"}}}
    patches = {"deps": {".._libs_dep": {"working_tree": DEP_DIFF}}}
    entry = rerun_features(vcs, [], metadata, patches)
    assert entry["changed"]["files"] == ["../libs/dep/util.py"]

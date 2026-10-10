"""Dep patches count in a run's features under the dep's configured path —
from a live capture (keyed by that path) and from a stored code object
(keyed by its safe name, mapped back through ``dep_base_commits``)."""
import types

import pytest
from vmn_exp.core import identity
from vmn_exp.gitmode.features import capture_features, rerun_features

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


def test_a_captured_dep_patch_is_listed_under_the_dep_path(vcs):
    captured = types.SimpleNamespace(identity={"deps": {"../libs/dep": {"working_tree": DEP_DIFF}}})
    entry = capture_features(vcs, captured)
    assert entry["changed"]["files"] == ["../libs/dep/util.py"]


def test_a_stored_dep_patch_is_listed_under_the_dep_path_it_was_captured_from(vcs):
    metadata = {"dep_base_commits": {"../libs/dep": "abc1234"}}
    patches = {"deps": {".._libs_dep": {"working_tree": DEP_DIFF}}}
    entry = rerun_features(vcs, [], metadata, patches)
    assert entry["changed"]["files"] == ["../libs/dep/util.py"]

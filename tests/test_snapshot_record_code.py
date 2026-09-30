"""build_record_metadata with a precomputed diff hash and a stored code object."""
from types import SimpleNamespace

import pytest

from version_stamp.snapshot import identity, record

VER_INFO = {"stamping": {"app": {"changesets": {}}}}
COMMIT = "abcdef1" + "0" * 33


def _vcs():
    backend = SimpleNamespace(active_branch="main", remote=lambda: None)
    return SimpleNamespace(backend=backend, name="app")


def _build(**kwargs):
    return record.build_record_metadata(
        _vcs(), "0.0.1-dev.abcdef1.1234567", "0.0.1", COMMIT, ["modified"],
        {"working_tree": "diff\n"}, VER_INFO, **kwargs,
    )


def test_a_given_diff_hash_is_not_recomputed(monkeypatch):
    def boom(_patches):
        raise AssertionError("re-hashed")

    monkeypatch.setattr(identity, "_compute_diff_hash", boom)
    meta = _build(diff_hash="1234567" + "f" * 57)
    assert meta["diff_hash"] == "1234567" + "f" * 57
    assert meta["code_verstr"] == "0.0.1-dev.abcdef1.1234567"


def test_code_adds_the_key_and_the_stored_summary():
    summary = {"has_working_tree_patch": True, "has_untracked_files": True}
    meta = _build(diff_hash="1234567" + "f" * 57, code=("the-key", summary), note="n")
    assert meta["code"] == "the-key"
    assert meta["has_untracked_files"] is True
    assert meta["note"] == "n"


@pytest.mark.parametrize("code", [None, (None, {"has_working_tree_patch": False})])
def test_no_code_key_leaves_code_out(code):
    meta = _build(code=code)
    assert "code" not in meta

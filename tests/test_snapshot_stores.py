"""open_snapshot_stores: the registered opener first, else the local stores."""
import os
from types import SimpleNamespace

import pytest

from version_stamp.cli import plugin_api
from version_stamp.snapshot import identity
from version_stamp.snapshot.stores import (
    SnapshotStoreError,
    SnapshotStores,
    open_snapshot_stores,
)


@pytest.fixture(autouse=True)
def no_opener(monkeypatch):
    monkeypatch.setattr(plugin_api, "_snapshot_store_opener", None)


def _vcs(tmp_path):
    return SimpleNamespace(vmn_root_path=str(tmp_path), name="app")


def test_without_opener_stores_are_local(tmp_path):
    stores = open_snapshot_stores(_vcs(tmp_path), {})
    assert stores.where == "local"
    stores.records.save("app", "v", {"verstr": "v"}, {})
    stores.code.save("vmn-code/app", "k", {"verstr": "k"}, {})
    assert os.path.isdir(tmp_path / ".vmn" / "app" / "snapshots" / "v")
    assert os.path.isdir(tmp_path / ".vmn" / "vmn-code" / "app" / "experiments" / "k")
    assert stores.records.code_store is stores.code


def test_store_flag_without_opener_is_an_error(tmp_path):
    with pytest.raises(SnapshotStoreError, match="pip install vmn-exp"):
        open_snapshot_stores(_vcs(tmp_path), {"store": "s3://b/p"})


def test_registered_opener_is_used(tmp_path):
    opened = SnapshotStores(records="r", code="c", where="s3://b/p")
    calls = []
    plugin_api.register_snapshot_store_opener(lambda vcs, params: calls.append(params) or opened)
    assert plugin_api.snapshot_store_opener() is not None
    assert open_snapshot_stores(_vcs(tmp_path), {"store": "s3://b/p"}) is opened
    assert calls == [{"store": "s3://b/p"}]


def test_opener_returning_none_falls_back_to_local(tmp_path):
    plugin_api.register_snapshot_store_opener(lambda vcs, params: None)
    assert open_snapshot_stores(_vcs(tmp_path), {}).where == "local"


def test_local_flag_skips_the_opener(tmp_path):
    plugin_api.register_snapshot_store_opener(lambda vcs, params: pytest.fail("called"))
    stores = open_snapshot_stores(_vcs(tmp_path), {"local": True, "store": "s3://b"})
    assert stores.where == "local"


def test_same_state_compares_diff_hash_and_dep_commits():
    changesets = {".": {"hash": "a"}, "../dep": {"hash": "b", "state": ["clean"]}}
    stored = {"diff_hash": "h", "changesets": changesets}
    assert identity.same_state(stored, "h", {".": {"hash": "a"}, "../dep": {"hash": "b"}})
    assert not identity.same_state(stored, "h", {".": {"hash": "a"}, "../dep": {"hash": "c"}})
    assert not identity.same_state(stored, "other", changesets)
    assert not identity.same_state({"changesets": changesets}, "h", changesets)

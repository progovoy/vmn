"""``local_side(storage)``: where a command's writes to *storage* land on
this host — a local-first cache's local store (with a remote or without),
a plain local store itself, and nothing for a store that is remote only."""
from types import SimpleNamespace

from vmn_exp.storage.cached import CachedSnapshotStorage, local_side
from vmn_exp.storage.local import LocalSnapshotStorage


def _local(tmp_path, name="local"):
    return LocalSnapshotStorage(str(tmp_path / name))


def test_a_cache_writes_to_its_local_side_with_or_without_a_remote(tmp_path):
    local = _local(tmp_path)
    assert local_side(CachedSnapshotStorage(local)) is local
    assert local_side(CachedSnapshotStorage(local, _local(tmp_path, "remote"))) is local


def test_a_local_store_is_its_own_local_side(tmp_path):
    local = _local(tmp_path)
    assert local_side(local) is local


def test_a_remote_only_store_has_no_local_side():
    assert local_side(SimpleNamespace(is_remote=lambda: True)) is None

"""Scale guard: every leaderboard request looks its app's index up by the
storage's ``cache_identity()``. Resolving the root with ``realpath`` there
costs an ``lstat`` per path component — syscalls that each hand the GIL to a
busy request thread, which under load made the lookup itself a hotspot.
The root is resolved once per storage object."""
import os

from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.open import open_storage


def _count_realpath(monkeypatch):
    calls = []
    real = os.path.realpath

    def counted(path, *args, **kwargs):
        calls.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", counted)
    return calls


def test_local_cache_identity_resolves_the_root_once(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path), area="runs")
    calls = _count_realpath(monkeypatch)
    identities = {st.cache_identity() for _ in range(100)}
    assert identities == {("local", os.path.realpath(str(tmp_path)), "runs")}
    assert len(calls) <= 2  # one lookup, plus the assertion's own


def test_cached_storage_identity_resolves_the_root_once(tmp_path, monkeypatch):
    st = open_storage(root=str(tmp_path), area="runs")
    calls = _count_realpath(monkeypatch)
    first = st.cache_identity()
    for _ in range(100):
        assert st.cache_identity() == first
    assert len(calls) <= 1

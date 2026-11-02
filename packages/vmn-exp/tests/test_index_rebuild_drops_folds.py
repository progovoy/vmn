"""A cache rebuild loads its index cold into a build store that its commit
closes; the live index adopting it then serves from another store. So the
rebuild keeps its folds, and the live index drops them once adopted, reading
them back from the store it serves from — never from the closed build store
(plan 28 appendix A row 6, mitigation 1)."""
import os
import shutil

import pytest
import scale_store
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_lazy import LazyRecord
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui import cache_resync

N = 50
APP = scale_store.APP


class _Remote(LocalSnapshotStorage):
    def is_remote(self):
        return True


@pytest.fixture
def store_root(tmp_path):
    root = str(tmp_path / "repo")
    scale_store.generate(root, N, workers=2)
    return root


def _storage(root):
    return _Remote(os.path.join(root, ".vmn", "store"), area="runs")


def _lazy_stores(index):
    return {id(record._fetch._store) for record in index._records.values()
            if isinstance(record, LazyRecord)}


def test_a_rebuild_keeps_its_folds_for_the_index_that_adopts_it(store_root, tmp_path):
    live = ExperimentIndex(_storage(store_root), APP, cache_path=str(tmp_path / "live.sqlite"))
    live.refresh()
    build_path = str(tmp_path / "build.sqlite")
    build_store = SqliteStore(build_path)
    fresh = cache_resync._build(_storage(store_root), APP, build_store, live)
    assert not _lazy_stores(fresh)  # no record bound to the build store
    build_store.close()
    shutil.copy(build_path, str(tmp_path / "served.sqlite"))
    served = SqliteStore(str(tmp_path / "served.sqlite"))

    live.adopt(fresh, served)
    live.refresh()

    assert _lazy_stores(live) == {id(served)}
    assert len(live.snapshot().rows) == N

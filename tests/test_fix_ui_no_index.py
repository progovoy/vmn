"""``vmn ui --no-index``: the same snapshot read path, over an index that keeps
no on-disk cache."""
import os

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.cli.snapshot_storage_files import INDEX_CACHE_FILE
from version_stamp.ui.experiment_source import ExperimentSource
from version_stamp.ui.workspaces import Workspace

APP = "app"


def _setup(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    source = ExperimentSource(str(tmp_path / "data"), use_index=False)
    return Workspace(name="ws", path=str(root)), storage, source


def _save(storage, i, parent=None):
    verstr = f"1.0.0-dev.r{i}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z", "parent": parent}
    storage.save(APP, verstr, meta, {})
    return verstr


def _files_under(path):
    return [os.path.join(d, f) for d, _, files in os.walk(path) for f in files]


def test_no_index_serves_a_snapshot_that_sees_every_write(tmp_path):
    ws, storage, source = _setup(tmp_path)
    outer = _save(storage, 0)
    _save(storage, 1, parent=outer)
    assert [r["verstr"] for r in source.snapshot(ws, APP).rows] == [outer, "1.0.0-dev.r1"]

    _save(storage, 2)
    assert len(source.snapshot(ws, APP).rows) == 3


def test_no_index_keeps_no_on_disk_cache(tmp_path):
    ws, storage, source = _setup(tmp_path)
    _save(storage, 0)
    source.snapshot(ws, APP)
    assert not os.path.exists(tmp_path / "data" / "index")
    assert not [p for p in _files_under(tmp_path / "repo") if INDEX_CACHE_FILE in p]


def test_no_index_detail_reads_edges_from_the_snapshot(tmp_path):
    ws, storage, source = _setup(tmp_path)
    outer = _save(storage, 0)
    inner = _save(storage, 1, parent=outer)
    snap = source.snapshot(ws, APP)
    options = source.detail_options(ws, snap)
    assert options["edges"](storage, APP) == {outer: None, inner: outer}
    assert options["resolve"]("@2") == (inner, None)

"""``vmn-exp prune -v <ref>`` keeps a run with a surviving child even when the
child has no marker: a store whose markers are not known complete is scanned
once (and, unless dry run, its markers and completeness flag written), and a
backend without markers is checked against every run's ``parent`` field."""
from types import SimpleNamespace

import pytest
import yaml

import vmn_exp.core.index as experiment_index
from vmn_exp.cli import prune as prune_mod
from vmn_exp.storage.local import LocalSnapshotStorage
from version_stamp.core.logging import init_stamp_logger

APP = "app"
RUNS = [f"0.0.1-dev.abc1234.r{i}" for i in range(3)]


@pytest.fixture(autouse=True)
def _logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


def _finished():
    return {"state": "finished", "exit_code": 0, "heartbeat": "2026-01-01T00:00:00Z",
            "heartbeat_interval_sec": 30}


def _save(storage, verstr, second, parent=None):
    """A finished run; a child is saved the way old stores hold it: no marker."""
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    storage.save(APP, verstr, meta, {})
    storage.save_file(APP, verstr, "run_state.yml", yaml.dump(_finished()))


def _old_store(storage):
    """r0 <- r1 (child without a marker), r2 independent."""
    _save(storage, RUNS[0], 0)
    _save(storage, RUNS[1], 1, parent=RUNS[0])
    _save(storage, RUNS[2], 2)
    return storage


@pytest.fixture
def st(tmp_path):
    return _old_store(LocalSnapshotStorage(str(tmp_path / "experiments")))


class NoMarkerStorage(LocalSnapshotStorage):
    """A backend without child markers (a plugin's, say)."""

    has_child_markers = False

    def mark_child(self, app_name, parent, child):
        return False

    def list_children(self, app_name, parent):
        return []


def _args(*refs, **kw):
    base = dict(version=list(refs), keep=None, older_than=None, force=False,
                dry_run=False, query=None, protect_tag=None)
    return SimpleNamespace(**dict(base, **kw))


def _prune(storage, *refs, **kw):
    return prune_mod.experiment_prune(None, {}, storage, _args(*refs, **kw), APP)


def _left(storage):
    return [v for v in RUNS if storage.exists(APP, v)]


def _forbid_listing(storage, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("a targeted prune must not list the app again")

    monkeypatch.setattr(prune_mod, "indexed_snapshot", forbidden)
    monkeypatch.setattr(experiment_index, "indexed_snapshot", forbidden)
    for name in ("list_verstrs", "list_snapshots", "list_record_names"):
        monkeypatch.setattr(storage, name, forbidden)


def test_first_targeted_prune_keeps_the_parent_of_a_markerless_child(st, capfd):
    assert _prune(st, RUNS[0]) == 0

    assert _left(st) == RUNS
    out, err = capfd.readouterr()
    assert "Nothing to prune" in out
    assert f"Indexing child links of {APP} once (3 runs)" in err


def test_first_targeted_prune_writes_the_markers_and_the_flag(st):
    assert not st.children_complete(APP)

    assert _prune(st, RUNS[2]) == 0

    assert st.children_complete(APP)
    assert st.list_children(APP, RUNS[0]) == [RUNS[1]]
    assert _left(st) == RUNS[:2]


def test_second_targeted_prune_reads_only_its_targets(st, monkeypatch, capfd):
    assert _prune(st, RUNS[2]) == 0
    capfd.readouterr()
    _forbid_listing(st, monkeypatch)

    assert _prune(st, RUNS[0]) == 0
    assert _left(st) == RUNS[:2]
    assert _prune(st, RUNS[1]) == 0

    assert _left(st) == [RUNS[0]]
    assert "Indexing child links" not in capfd.readouterr().err


def test_targeted_dry_run_protects_yet_writes_nothing(st, capfd):
    assert _prune(st, RUNS[0], dry_run=True) == 0

    assert "Nothing to prune" in capfd.readouterr().out
    assert not st.children_complete(APP)
    assert st.list_children(APP, RUNS[0]) == []


def test_targeted_dry_run_still_previews_an_unguarded_run(st, capfd):
    assert _prune(st, RUNS[2], dry_run=True) == 0

    assert "Would delete 1 experiments" in capfd.readouterr().out
    assert _left(st) == RUNS
    assert not st.children_complete(APP)


def test_a_store_flagged_complete_trusts_its_markers(st, monkeypatch):
    st.mark_child(APP, RUNS[0], RUNS[1])
    st.set_children_complete(APP, True)
    _forbid_listing(st, monkeypatch)

    assert _prune(st, RUNS[0]) == 0
    assert _left(st) == RUNS
    assert _prune(st, RUNS[0], RUNS[1]) == 0
    assert _left(st) == [RUNS[2]]


def test_a_backend_without_markers_protects_by_a_full_scan(tmp_path, capfd):
    storage = _old_store(NoMarkerStorage(str(tmp_path / "plugin")))

    assert _prune(storage, RUNS[0]) == 0
    assert _left(storage) == RUNS
    assert "Nothing to prune" in capfd.readouterr().out

    assert _prune(storage, RUNS[0], RUNS[1]) == 0
    assert _left(storage) == [RUNS[2]]
    assert not storage.children_complete(APP)


def test_a_backend_without_markers_keeps_a_grandparent(tmp_path):
    storage = _old_store(NoMarkerStorage(str(tmp_path / "plugin")))
    grandkid = "0.0.1-dev.abc1234.r9"
    _save(storage, grandkid, 9, parent=RUNS[1])

    assert _prune(storage, RUNS[0], RUNS[1]) == 0

    assert _left(storage) == RUNS

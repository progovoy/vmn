"""Once a cold (remote) load has published and persisted its rows, the index
keeps what a warm restart keeps: each record its run state alone, read back
from the persisted index when a refresh needs it (plan 28 appendix A row 6,
mitigation 1). A free-threaded collection walks every live object, so the
cold process's per-run folds (twice a warm one's objects) doubled its pauses.

Every reader answers the same as a warm restart, before and after the store
changes, and a generation's unchanged rows and run states stay the same
objects (readers diff generations by identity)."""
import gc
import os
import shutil

import pytest
import scale_store
from vmn_exp.core.index import ExperimentIndex, direct_rows
from vmn_exp.storage.local import LocalSnapshotStorage

N = 200
APP = scale_store.APP
SCHEMA = {"loss": {"goal": "min", "primary": True}}


class _Remote(LocalSnapshotStorage):
    def is_remote(self):
        return True


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = str(tmp_path_factory.mktemp("cold-folds") / "repo")
    scale_store.generate(root, N, workers=2)
    return root


@pytest.fixture
def store_root(generated, tmp_path):
    root = str(tmp_path / "repo")
    shutil.copytree(generated, root)
    return root


def _storage(root, cls=_Remote):
    return cls(os.path.join(root, ".vmn", "store"), area="runs")


def _cold(root, db, **kwargs):
    index = ExperimentIndex(_storage(root), APP, cache_path=db, **kwargs)
    index.refresh()
    return index


def _warm(root, db, **kwargs):
    index = ExperimentIndex(_storage(root), APP, cache_path=db, **kwargs)
    index.snapshot()
    index.wait_revalidated()
    return index


def _reachable(obj):
    """gc-tracked objects reachable from *obj* (classes and functions aside)."""
    seen, stack = set(), [obj]
    while stack:
        o = stack.pop()
        if id(o) in seen or not gc.is_tracked(o) or isinstance(o, type) or (
                callable(o) and not isinstance(o, dict)):
            continue
        seen.add(id(o))
        stack.extend(gc.get_referents(o))
    return len(seen)


def _answers(index):
    snap = index.snapshot()
    verstrs = [row["verstr"] for row in snap.rows]
    return {
        "rows": index.rows(with_create_note=True),
        "run_states": index.run_states(),
        "summarized": list(snap.summarized(SCHEMA).rows),
        "sides": {v: (snap.features_of(v), snap.intent_of(v), snap.hypothesis_of(v),
                      snap.notes_of(v), snap.status_of(v)) for v in verstrs},
        "resolved": [snap.resolve(f"@{n}") for n in range(1, 21)],
    }


def test_a_cold_load_holds_what_a_warm_restart_holds(store_root, tmp_path):
    db = str(tmp_path / "idx.sqlite")
    cold = _cold(store_root, db)
    cold_records, cold_all = _reachable(cold._records), _reachable(cold)
    warm = _warm(store_root, db)
    warm_records, warm_all = _reachable(warm._records), _reachable(warm)
    assert len(cold.snapshot().rows) == len(warm.snapshot().rows) == N
    # A full fold is ~20 objects a run; a warm record ~5.
    assert cold_records / N <= warm_records / N + 1, (cold_records / N, warm_records / N)
    assert cold_all <= warm_all * 1.15, (cold_all / N, warm_all / N)


def test_readers_answer_as_after_a_warm_restart(store_root, tmp_path):
    db = str(tmp_path / "idx.sqlite")
    cold = _cold(store_root, db)
    assert _answers(cold) == _answers(_warm(store_root, db))


def test_a_no_change_refresh_keeps_the_generation(store_root, tmp_path):
    cold = _cold(store_root, str(tmp_path / "idx.sqlite"))
    snap = cold.snapshot()
    cold.refresh()
    assert cold.snapshot() is snap


def _change(storage, snap):
    """Append metrics to a finished run, end a running one, add one, delete one."""
    by_status = {}
    for row in snap.rows:
        by_status.setdefault(snap.status_of(row["verstr"]), []).append(row["verstr"])
    finished, running = by_status["succeeded"][0], by_status["running"][0]
    gone = by_status["failed"][0]
    storage.append_log_entry(APP, finished, "w9", {
        "timestamp": "2026-01-02T00:00:00Z", "type": "metrics", "step": 10_000,
        "values": {"loss": 0.001, "late": 1.0}})
    storage.save_file(APP, running, "run_state.yml",
                      "state: finished\nexit_code: 0\npid: 1\nhost: h\n")
    storage.save(APP, "9.9.9", {"verstr": "9.9.9", "timestamp": "2027-01-01T00:00:00Z"}, {})
    storage.save_file(APP, "9.9.9", "run_state.yml", "state: finished\nexit_code: 0\n")
    storage.delete(APP, gone)
    return finished, running, gone


def test_refresh_deltas_after_the_drop_match_a_warm_restart(store_root, tmp_path):
    db = str(tmp_path / "idx.sqlite")
    cold = _cold(store_root, db, full_sweep_sec=0)
    before = cold.snapshot()
    finished, running, gone = _change(_storage(store_root), before)
    cold.refresh()
    after = cold.snapshot()
    assert after.generation > before.generation
    assert after.row(finished)["metrics"]["late"] == 1.0
    assert after.status_of(running) == "succeeded"
    assert after.row("9.9.9") is not None and after.row(gone) is None
    assert _answers(cold) == _answers(_warm(store_root, db, full_sweep_sec=0))
    reference, _ = direct_rows(_storage(store_root), APP, with_create_note=True)
    assert cold.rows(with_create_note=True) == reference


def test_a_generation_keeps_its_unchanged_rows_and_run_states(store_root, tmp_path):
    cold = _cold(store_root, str(tmp_path / "idx.sqlite"), full_sweep_sec=0)
    before = cold.snapshot()
    finished, running, gone = _change(_storage(store_root), before)
    cold.refresh()
    after = cold.snapshot()
    rows_before = {row["verstr"]: row for row in before.rows}
    changed = {finished, running, gone, "9.9.9"}
    for row in after.rows:
        verstr = row["verstr"]
        if verstr in changed:
            continue
        # idx moved by the removal: re-numbered copies, the same run state.
        assert dict(row, idx=0) == dict(rows_before[verstr], idx=0)
        assert after.run_states[verstr] is before.run_states[verstr]


def test_an_index_without_a_persisted_store_keeps_its_folds(store_root):
    index = ExperimentIndex(_storage(store_root), APP, full_sweep_sec=0)
    index.refresh()
    finished, _, _ = _change(_storage(store_root), index.snapshot())
    index.refresh()
    assert index.snapshot().row(finished)["metrics"]["late"] == 1.0
    reference, _ = direct_rows(_storage(store_root), APP, with_create_note=True)
    assert index.rows(with_create_note=True) == reference

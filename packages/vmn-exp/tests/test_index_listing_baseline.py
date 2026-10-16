"""Plan 25 F2: the listing baselines persist, so a cold process lists record
names once and re-reads only what moved; a full stat sweep runs at most every
``full_sweep_sec`` (300 s) across processes."""
import os

import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_sweep
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
RUNNING = "state: running\nheartbeat: '2026-01-01T00:00:00Z'\n"


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clocks(monkeypatch):
    """``(monotonic, wall)``: each process gets its own monotonic origin."""
    mono, wall = Clock(1000.0), Clock(1_800_000_000.0)
    monkeypatch.setattr(experiment_index, "_monotonic", mono)
    monkeypatch.setattr(index_sweep, "_wall", wall)
    return mono, wall


@pytest.fixture
def root(tmp_path):
    return str(tmp_path / "store")


@pytest.fixture
def cache(tmp_path):
    return str(tmp_path / "index.sqlite")


def _make(st, i, run_state=FINISHED):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                            "values": {"loss": float(i)}})
    st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


class Process:
    """A fresh storage object and index over the same store and cache — what
    a new CLI process starts with — recording what it lists and re-reads."""

    def __init__(self, root, cache, clocks, monkeypatch, advance=0.0):
        mono, wall = clocks
        mono.now += 5000.0  # another process: another monotonic origin
        wall.now += advance
        self.storage = LocalSnapshotStorage(root, area="runs")
        self.listed, self.updated = [], []
        real_list, real_update = self.storage.list_files, experiment_index.update_record

        def list_files(app_name, keys=None, **kwargs):
            self.listed.append(None if keys is None else set(keys))
            return real_list(app_name, keys=keys, **kwargs)

        def update_record(storage, direct, app_name, key, names, record):
            self.updated.append(key)
            return real_update(storage, direct, app_name, key, names, record)

        monkeypatch.setattr(self.storage, "list_files", list_files)
        monkeypatch.setattr(experiment_index, "update_record", update_record)
        self.index = ExperimentIndex(self.storage, APP, cache_path=cache)

    def refresh(self):
        self.index.refresh()
        return self

    def row(self, verstr):
        return next(r for r in self.index.rows() if r["verstr"] == verstr)


@pytest.fixture
def process(root, cache, clocks, monkeypatch):
    return lambda advance=1.0: Process(root, cache, clocks, monkeypatch, advance)


def test_the_full_sweep_runs_every_300_seconds_by_default():
    assert index_sweep.DEFAULT_FULL_SWEEP_SEC == 300
    assert ExperimentIndex(None, APP).full_sweep_sec == 300


def test_a_cold_refresh_after_one_changed_run_re_reads_only_that_run(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    runs = [_make(st, i) for i in range(5)]
    assert process().refresh().listed == [None]  # no baseline yet: a full sweep

    st.append_log_entry(APP, runs[2], "w", {"timestamp": "u", "type": "metrics",
                                             "values": {"loss": 0.25}})
    cold = process().refresh()
    assert cold.listed == [{runs[2]}]
    assert cold.updated == [runs[2]]
    assert cold.row(runs[2])["metrics"]["loss"] == 0.25
    assert len(cold.index.rows()) == 5


def test_a_cold_refresh_with_nothing_changed_lists_no_files(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    [_make(st, i) for i in range(3)]
    process().refresh()
    cold = process().refresh()
    assert cold.listed == []
    assert cold.updated == []
    assert len(cold.index.rows()) == 3


def test_a_new_run_is_loaded_by_a_cold_refresh_without_a_full_sweep(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    _make(st, 1)
    process().refresh()
    new = _make(st, 2)
    cold = process().refresh()
    assert cold.listed == [{new}]
    assert [r["verstr"] for r in cold.index.rows()][-1] == new


def test_a_deleted_run_disappears_as_soon_as_its_name_is_gone(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    runs = [_make(st, i) for i in range(3)]
    process().refresh()
    st.delete(APP, runs[1])
    cold = process().refresh()
    assert None not in cold.listed
    assert [r["verstr"] for r in cold.index.rows()] == [runs[0], runs[2]]


def test_a_live_run_is_always_re_listed_by_a_cold_process(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    _make(st, 1)
    live = _make(st, 2, RUNNING)
    process().refresh()
    assert process().refresh().listed == [{live}]


def test_a_recently_changed_run_is_re_listed_by_a_cold_process(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    done, _ = _make(st, 1), _make(st, 2)
    warm = process().refresh()
    st.append_log_entry(APP, done, "w", {"timestamp": "u", "type": "note"})
    warm.refresh()  # sees the change: the run is touched

    assert process(advance=10).refresh().listed == [{done}]
    # Past the touch window it goes quiet (and a full sweep is due).
    assert process(advance=600).refresh().listed == [None]


def _rewrite_in_place(st, verstr, note):
    """Change *verstr*'s metadata the way no vmn write does: in place, the
    record directory's signature restored, so no names listing can see it."""
    folder = st._snapshot_dir(APP, verstr)
    before = os.stat(folder)
    path = os.path.join(folder, "metadata.yml")
    with open(path) as f:
        text = f.read()
    with open(path, "w") as f:
        f.write(text + f"note: {note}\n")
    os.utime(folder, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_an_unsignalled_change_to_a_finished_run_is_caught_by_the_full_sweep(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    verstr = _make(st, 1)
    process().refresh()
    _rewrite_in_place(st, verstr, "edited")

    soon = process(advance=10).refresh()
    assert None not in soon.listed and soon.row(verstr)["note"] is None
    # 300 s after the first process's full sweep, whoever refreshes runs one.
    due = process(advance=291).refresh()
    assert due.listed == [None]
    assert due.row(verstr)["note"] == "edited"
    # ... and the next process trusts it for another 300 s.
    assert None not in process(advance=5).refresh().listed


def test_a_failed_save_persists_no_baseline(root, process, monkeypatch):
    st = LocalSnapshotStorage(root, area="runs")
    _make(st, 1)
    first = process()
    monkeypatch.setattr(first.index._store, "save", lambda *a, **k: False)
    first.refresh()
    assert process().refresh().listed == [None]


def test_baselines_are_per_app(root, process):
    st = LocalSnapshotStorage(root, area="runs")
    _make(st, 1)
    process().refresh()
    other = process()
    other.index = ExperimentIndex(other.storage, "other", cache_path=other.index._cache_path)
    st.save("other", "0.0.2", {"verstr": "0.0.2", "timestamp": "t"}, {})
    other.refresh()
    assert other.listed == [None]


def test_a_file_saved_into_a_records_log_folder_moves_its_signature(root):
    # The names listing signs a record by its directory; a write into log/
    # renames inside log/ only, so the save itself has to move it.
    st = LocalSnapshotStorage(root, area="runs")
    verstr = _make(st, 1)
    before = st.list_record_names(APP)[verstr]
    st.save_file(APP, verstr, "log/w.jsonl", '{"timestamp": "u", "type": "note"}\n')
    assert st.list_record_names(APP)[verstr] != before

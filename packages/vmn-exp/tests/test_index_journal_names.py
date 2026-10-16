"""Plan 25 §1 ("refresh after 100 changed runs ≤ 0.2 s"): over a journaled
local store, a refresh between full sweeps neither lists nor signs every
record directory — what was created, changed or removed since the previous
listing comes from the store's change journal — and still re-reads exactly
the records that moved."""
import pytest

from vmn_exp.core import index as experiment_index
from vmn_exp.core import index_journal_names, index_sweep
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.journal import journaled

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def journal_at_any_size(monkeypatch):
    monkeypatch.setattr(index_journal_names, "MIN_RECORDS", 0)


@pytest.fixture
def clocks(monkeypatch):
    mono, wall = Clock(1000.0), Clock(1_800_000_000.0)
    monkeypatch.setattr(experiment_index, "_monotonic", mono)
    monkeypatch.setattr(index_sweep, "_wall", wall)
    return mono, wall


def _make(st, i):
    verstr = f"0.0.1-dev.abc.r{i}"
    st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z"}, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return verstr


class Process:
    """A fresh journaled storage and index over the same store and cache."""

    def __init__(self, root, cache, clocks, monkeypatch, advance):
        mono, wall = clocks
        mono.now += 5000.0
        wall.now += advance
        self.storage = journaled(LocalSnapshotStorage(root, area="runs"), clock=wall)
        self.updated, self.signed, self.scanned = [], [], []
        real_update = experiment_index.update_record
        real_names = LocalSnapshotStorage.list_record_names
        real_keys = LocalSnapshotStorage.list_record_keys

        def update_record(storage, direct, app_name, key, names, record):
            self.updated.append(key)
            return real_update(storage, direct, app_name, key, names, record)

        def list_record_names(storage, app_name):
            self.signed.append(app_name)
            return real_names(storage, app_name)

        monkeypatch.setattr(experiment_index, "update_record", update_record)
        def list_record_keys(storage, app_name):
            self.scanned.append(app_name)
            return real_keys(storage, app_name)

        monkeypatch.setattr(LocalSnapshotStorage, "list_record_names", list_record_names)
        monkeypatch.setattr(LocalSnapshotStorage, "list_record_keys", list_record_keys)
        self.index = ExperimentIndex(self.storage, APP, cache_path=cache)

    def rows(self):
        return {r["verstr"]: r for r in self.index.refresh().rows()}


@pytest.fixture
def process(tmp_path, clocks, monkeypatch):
    root, cache = str(tmp_path / "store"), str(tmp_path / "index.sqlite")
    return lambda advance=1.0: Process(root, cache, clocks, monkeypatch, advance)


@pytest.fixture
def seeded(process, clocks):
    first = process()
    # Written before the skew window: the next listings need not look again.
    first.storage._journal_state.clock = Clock(clocks[1].now - 2 * index_journal_names.SKEW_SEC)
    runs = [_make(first.storage, i) for i in range(20)]
    first.rows()  # the first listing is a full one
    return runs


def test_a_refresh_between_sweeps_signs_no_record(process, seeded):
    later = process()
    later.storage.update_note(APP, seeded[3], "edited")
    new = _make(later.storage, 50)
    again = process()
    rows = again.rows()
    assert again.signed == again.scanned == []  # the journal named both
    assert rows[seeded[3]]["note"] == "edited" and new in rows
    assert sorted(again.updated) == sorted([seeded[3], new])


def test_a_sync_after_a_cold_build_reads_only_the_changed_record(process, seeded, monkeypatch):
    """The build judged each record it loaded: the next refresh does not
    read every persisted record back to judge it again."""
    from vmn_exp.core.index_lazy import LazyRecord
    from vmn_exp.core.index_store import SqliteStore

    process().storage.update_note(APP, seeded[3], "edited")
    read, head = [], LazyRecord._head
    monkeypatch.setattr(LazyRecord, "_head", lambda self: (read.append(self._key), head(self)))
    fetched, parts = [], SqliteStore.records_parts
    monkeypatch.setattr(SqliteStore, "records_parts",
                        lambda self, app, seqs: (fetched.extend(seqs), parts(self, app, seqs))[1])
    again = process()
    assert again.index.sync() and again.signed == []
    assert set(read) == set(fetched) == {seeded[3]}


def test_a_record_removed_since_is_gone(process, seeded):
    process().storage.delete(APP, seeded[5])
    again = process()
    assert seeded[5] not in again.rows() and again.signed == again.scanned == []


def test_a_change_journaled_late_within_the_skew_window_is_seen(process, seeded, clocks):
    writer = process()
    writer.storage._journal_state.clock = Clock(clocks[1].now - 120.0)  # a slow writer clock
    writer.storage.update_note(APP, seeded[1], "skewed")
    assert process().rows()[seeded[1]]["note"] == "skewed"


def test_a_journal_too_busy_to_read_falls_back_to_signing(process, seeded, monkeypatch):
    monkeypatch.setattr(index_journal_names, "MAX_ENTRIES", 1)
    writer = process()
    writer.storage.update_note(APP, seeded[1], "one")
    writer.storage.update_note(APP, seeded[2], "two")
    again = process()
    rows = again.rows()
    assert again.signed == [APP]
    assert rows[seeded[1]]["note"] == "one" and rows[seeded[2]]["note"] == "two"


def test_an_unjournaled_store_signs_every_record(tmp_path, clocks, monkeypatch):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    verstr = _make(storage, 1)
    index = ExperimentIndex(storage, APP, cache_path=str(tmp_path / "index.sqlite"))
    index.refresh()
    storage.update_note(APP, verstr, "seen by its signature")
    clocks[0].now += 1.0
    assert index.refresh().rows()[0]["note"] == "seen by its signature"


def test_a_refresh_rewrites_only_the_baseline_of_the_records_it_moved(process, clocks, monkeypatch):
    from vmn_exp.core.index_store import SqliteStore

    first = process()
    first.storage._journal_state.clock = Clock(clocks[1].now - 2 * index_journal_names.SKEW_SEC)
    runs = [_make(first.storage, i) for i in range(3000)]
    first.rows()
    writer = process()
    for verstr in runs[::300]:
        writer.storage.update_note(APP, verstr, "moved")
    written, put_many = [], SqliteStore.kv_put_many
    monkeypatch.setattr(SqliteStore, "kv_put_many", lambda self, puts: (
        written.extend(len(p) for scope, _, p in puts if scope.count(":") == 2),
        put_many(self, puts))[1])
    process().rows()
    assert 0 < sum(written) <= 10 * 100  # ten records' shards of at most 100 records each

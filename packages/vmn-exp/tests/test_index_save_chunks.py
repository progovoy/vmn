"""No single save transaction holds a whole cold load: a refresh persists its
records a chunk at a time, through the I/O helper process too."""
import pytest
from vmn_exp.core import index_pending
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_io_process import _Helper
from vmn_exp.core.index_pending import PendingSave
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"


@pytest.fixture(autouse=True)
def small_chunks(monkeypatch):
    monkeypatch.setattr(index_pending, "SAVE_CHUNK", 2)


@pytest.fixture
def saves(monkeypatch):
    """``(changed keys, state keys, removed, kv_puts)`` per SqliteStore.save."""
    calls, real = [], SqliteStore.save

    def spy(self, app, changed, removed, states=None, kv_puts=None):
        calls.append((set(changed), set(states or ()), set(removed), kv_puts))
        return real(self, app, changed, removed, states, kv_puts)

    monkeypatch.setattr(SqliteStore, "save", spy)
    return calls


def _storage(tmp_path, runs=5):
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    for i in range(runs):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {})
        st.save_file(APP, verstr, "run_state.yml", FINISHED)
    return st


def test_the_io_helper_saves_a_cold_load_in_chunks(tmp_path, saves):
    st, db = _storage(tmp_path), str(tmp_path / "idx.sqlite")
    helper = _Helper(st.io_process_args(), APP, db)
    work = [(key, names, None) for key, names in st.list_files(APP).items()]

    helper.refresh(work, set())

    record_saves = [c for c in saves if c[0] or c[1]]
    assert len(record_saves) == 3
    assert all(len(changed | states) <= 2 for changed, states, _, _ in record_saves)
    assert len(SqliteStore(db).load(APP)) == 5
    assert SqliteStore(db).generation(APP) == 3


def test_an_in_process_cold_refresh_saves_in_chunks_too(tmp_path, saves):
    st, db = _storage(tmp_path), str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    record_saves = [c for c in saves if c[0] or c[1]]
    assert len(record_saves) == 3
    assert len(SqliteStore(db).load(APP)) == 5


class _Store:
    """Answers False from its *fail_at*-th save on."""

    def __init__(self, fail_at=None):
        self.calls, self._fail_at = [], fail_at

    def save(self, scope, changed, removed, states, kv_puts=None):
        self.calls.append((dict(changed), set(removed), dict(states), kv_puts))
        return self._fail_at is None or len(self.calls) < self._fail_at


def test_removals_and_kv_puts_go_with_the_last_chunk():
    store = _Store()
    changed = {f"k{i}": {"n": i} for i in range(5)}
    assert PendingSave().save(store, APP, changed, {"gone"}, {"k0": {}}, {"kv": 1}) is True
    assert [set(c) for c, _, _, _ in store.calls] == [{"k0", "k1"}, {"k2", "k3"}, {"k4"}]
    assert [r for _, r, _, _ in store.calls] == [set(), set(), {"gone"}]
    assert [kv for _, _, _, kv in store.calls] == [None, None, {"kv": 1}]
    assert store.calls[0][2] == {"k0": {}}


def test_a_failed_chunk_keeps_it_and_the_rest_pending():
    pending = PendingSave()
    changed = {f"k{i}": {"n": i} for i in range(5)}
    assert pending.save(_Store(fail_at=2), APP, changed, {"gone"}, {}) is False

    retry = _Store()
    assert pending.save(retry, APP, {}, set(), {}) is True
    assert set().union(*(c for c, _, _, _ in retry.calls)) == {"k2", "k3", "k4"}
    assert retry.calls[-1][1] == {"gone"}

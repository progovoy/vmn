"""Incremental refresh: a no-change refresh lists record names, then only the
new and live records' files; a periodic full sweep is the safety net."""
import os

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core import experiment_index
from version_stamp.core.experiment_index import ExperimentIndex

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(experiment_index, "_monotonic", c)
    return c


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


@pytest.fixture
def listed(st, monkeypatch):
    """``keys`` of every list_files call (None for a full listing)."""
    calls = []
    real = st.list_files

    def spy(app_name, keys=None):
        calls.append(None if keys is None else set(keys))
        return real(app_name, keys=keys)

    monkeypatch.setattr(st, "list_files", spy)
    return calls


def _make(st, i, run_state=None, note=None):
    verstr = f"0.0.1-dev.abc.r{i}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z", "note": note}
    st.save(APP, verstr, meta, {})
    st.append_log_entry(APP, verstr, "w", {"timestamp": "t", "type": "metrics",
                                            "values": {"loss": float(i)}})
    if run_state is not None:
        st.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


# -- storage listing ---------------------------------------------------------


def test_list_record_names_is_names_only(st):
    st.save(APP, "1.0.0-dev.a+b", {"verstr": "1.0.0-dev.a+b"}, {})
    st.save(APP, "1.0.0-dev.c", {"verstr": "1.0.0-dev.c"}, {})
    st.index_cache_path(APP)  # adds .gitignore next to the records
    open(os.path.join(st._snapshot_base_dir(APP), ".index.sqlite"), "w").close()

    names = st.list_record_names(APP)
    assert set(names) == {"1.0.0-dev.a+b", "1.0.0-dev.c"}
    folder = os.stat(st._snapshot_dir(APP, "1.0.0-dev.c"))
    assert names["1.0.0-dev.c"] == (folder.st_mtime_ns, folder.st_ino)
    assert st.list_record_names("missing") == {}


def test_an_atomic_write_changes_the_record_signature(st):
    verstr = _make(st, 1, FINISHED)
    before = st.list_record_names(APP)[verstr]
    st.update_note(APP, verstr, "renamed")
    assert st.list_record_names(APP)[verstr] != before


def test_list_files_can_be_limited_to_some_records(st):
    a, b = _make(st, 1), _make(st, 2)
    files = st.list_files(APP, keys=[a, "0.0.1-dev.nope"])
    assert set(files) == {a}
    assert files[a] == st.list_files(APP)[a]
    assert b not in files


# -- refresh -----------------------------------------------------------------


def test_a_no_change_refresh_lists_only_live_records(st, listed, clock):
    finished = [_make(st, i, FINISHED) for i in range(3)]
    live = _make(st, 5, "state: running\nheartbeat: '2026-01-01T00:00:00Z'\n")
    never_run = _make(st, 6)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()
    assert listed == [None]  # the first refresh is a full sweep

    clock.now += 1
    index.refresh()
    assert listed[1:] == [{live, never_run}]
    assert len(index.rows()) == 5
    assert set(index.run_states()) == set(finished) | {live, never_run}


def test_new_and_removed_records_are_seen_without_a_full_sweep(st, listed, clock):
    old = [_make(st, i, FINISHED) for i in range(2)]
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()

    new = _make(st, 7, FINISHED)
    st.delete(APP, old[0])
    clock.now += 1
    index.refresh()

    assert listed[1:] == [{new}]
    assert [r["verstr"] for r in index.rows()] == [old[1], new]
    assert [r["idx"] for r in index.rows()] == [1, 2]


def test_a_live_run_is_followed_until_it_finishes_and_a_while_after(st, clock):
    verstr = _make(st, 1, "state: running\n")
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()

    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    clock.now += 1
    index.refresh()
    assert index.run_states()[verstr]["exit_code"] == 0

    # Its last metrics may land just after the exit code.
    st.append_log_entry(APP, verstr, "w", {"timestamp": "u", "type": "metrics",
                                            "values": {"loss": 0.5}})
    clock.now += 1
    index.refresh()
    assert index.rows()[0]["metrics"]["loss"] == 0.5


def test_a_finished_run_goes_quiet_after_the_sweep_window(st, listed, clock):
    verstr = _make(st, 1, "state: running\n")
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()
    st.save_file(APP, verstr, "run_state.yml", FINISHED)
    clock.now += 1
    index.refresh()

    clock.now += 298
    del listed[:]
    index.refresh()  # changed 298s ago: still listed
    clock.now += 1
    index.refresh()  # a full sweep is due: 300s since the first one
    clock.now += 2
    index.refresh()  # quiet since the window closed: nothing to list
    assert listed == [{verstr}, None]


def test_a_note_on_a_finished_run_shows_up_at_the_next_full_sweep(st, clock):
    verstr = _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()

    st.update_note(APP, verstr, "renamed")
    clock.now += 301
    index.refresh()
    assert index.rows()[0]["note"] == "renamed"


def test_a_storage_without_names_listing_always_lists_everything(st, clock):
    class Plain:
        def __init__(self, inner):
            self._inner = inner
            self.calls = 0

        def list_files(self, app_name):
            self.calls += 1
            return self._inner.list_files(app_name)

        def load_file(self, *args):
            return self._inner.load_file(*args)

        def direct_files(self):
            return self._inner

    _make(st, 1, FINISHED)
    plain = Plain(st)
    index = ExperimentIndex(plain, APP)
    index.refresh()
    clock.now += 1
    index.refresh()
    assert plain.calls == 2
    assert len(index.rows()) == 1


def test_a_note_on_a_finished_run_shows_up_at_the_next_refresh(st, listed, clock):
    done, other = _make(st, 1, FINISHED), _make(st, 2, FINISHED)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()

    st.update_note(APP, done, "renamed")
    clock.now += 1
    index.refresh()

    assert listed[1:] == [{done}]
    assert index.rows()[0]["note"] == "renamed"
    assert other not in listed[1]


def test_an_exit_code_rewrite_on_a_finished_run_shows_up_at_the_next_refresh(st, clock):
    verstr = _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()

    st.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 9\n")
    clock.now += 1
    index.refresh()
    assert index.run_states()[verstr]["exit_code"] == 9


def test_names_without_signatures_wait_for_the_full_sweep(st, clock):
    class NamesOnly(LocalSnapshotStorage):
        def list_record_names(self, app_name):
            return set(super().list_record_names(app_name))

    names_only = NamesOnly(st.vmn_root_path, subdir="experiments")
    verstr = _make(names_only, 1, FINISHED)
    index = ExperimentIndex(names_only, APP, full_sweep_sec=300)
    index.refresh()

    names_only.update_note(APP, verstr, "renamed")
    clock.now += 1
    index.refresh()
    assert index.rows()[0]["note"] is None
    clock.now += 300
    index.refresh()
    assert index.rows()[0]["note"] == "renamed"


def test_a_backend_that_cannot_list_names_gets_a_full_listing(st, listed, clock):
    _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()
    st.list_record_names = lambda app_name: None
    clock.now += 1
    index.refresh()
    assert listed == [None, None]


# -- opting in -----------------------------------------------------------------


def test_by_default_every_refresh_is_a_full_listing(st, listed, clock):
    verstr = _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP)
    assert index.full_sweep_sec == 0
    index.refresh()
    folder = st._snapshot_dir(APP, verstr)
    with open(os.path.join(folder, "log.w.jsonl"), "a") as f:
        f.write('{"timestamp": "u", "type": "metrics", "values": {"loss": 0.5}}\n')
    index.refresh()
    assert listed == [None, None]
    assert index.rows()[0]["metrics"]["loss"] == 0.5


def test_the_fast_tier_can_be_switched_on_later(st, listed, clock):
    _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP)
    index.refresh()
    index.full_sweep_sec = 300
    clock.now += 1
    index.refresh()
    assert listed == [None]


def test_shared_index_and_indexed_snapshot_set_the_sweep_interval(st):
    index = experiment_index.shared_index(st, APP, full_sweep_sec=30)
    assert index.full_sweep_sec == 30
    assert experiment_index.shared_index(st, APP).full_sweep_sec == 30
    experiment_index.indexed_snapshot(st, APP, full_sweep_sec=5)
    assert index.full_sweep_sec == 5


def test_an_append_through_the_storage_bumps_the_record_signature(st):
    verstr = _make(st, 1, FINISHED)
    before = st.list_record_names(APP)[verstr]
    st.append_log_entry(APP, verstr, "w", {"timestamp": "u", "type": "note"})
    assert st.list_record_names(APP)[verstr] != before


def test_an_append_to_a_finished_run_shows_up_in_the_fast_tier(st, listed, clock):
    verstr = _make(st, 1, FINISHED)
    index = ExperimentIndex(st, APP, full_sweep_sec=300)
    index.refresh()
    st.append_log_entry(APP, verstr, "w", {"timestamp": "u", "type": "metrics",
                                            "values": {"loss": 0.25}})
    clock.now += 1
    index.refresh()
    assert listed[1:] == [{verstr}]
    assert index.rows()[0]["metrics"]["loss"] == 0.25

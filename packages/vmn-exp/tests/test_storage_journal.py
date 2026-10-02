"""The change-journal writer (plan 11 §5.2, phase 2a): every write that
changes what a reader sees puts one empty object under ``journal/``."""
import pytest
import yaml

from vmn_exp.core.journal_keys import decode_key
from vmn_exp.storage.journal import JournaledStorage, journaled
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "root_app/svc"
V1 = "1.2.0-dev.abc1234.0000001"


class RecordingSink:
    def __init__(self, fail=0):
        self.keys, self.fail, self.calls = [], fail, 0

    def put(self, key):
        self.calls += 1
        if self.fail:
            self.fail -= 1
            raise OSError("journal put failed")
        self.keys.append(key)


def _store(tmp_path, sink, **kw):
    return journaled(LocalSnapshotStorage(str(tmp_path), "runs"), sink=sink,
                     writer_id="host_1", backoff=lambda attempt: None, **kw)


@pytest.fixture
def sink():
    return RecordingSink()


@pytest.fixture
def store(tmp_path, sink):
    return _store(tmp_path, sink)


def _claimed(store):
    assert store.create_exclusive(APP, V1, {"verstr": V1}, {})
    return store


def _entries(sink):
    return [decode_key(k) for k in sink.keys]


def test_claim_puts_one_entry_with_area_app_and_name(store, sink):
    _claimed(store)
    [entry] = _entries(sink)
    assert (entry.area, entry.app_key, entry.name) == ("runs", "root_app-svc", V1)
    assert entry.writer_id == "host_1"


def test_a_lost_claim_puts_nothing(store, sink):
    _claimed(store)
    assert not store.create_exclusive(APP, V1, {"verstr": V1}, {})
    assert len(sink.keys) == 1


def test_wrapper_keeps_the_inner_type(store):
    assert isinstance(store, LocalSnapshotStorage)
    assert isinstance(store, JournaledStorage)


@pytest.mark.parametrize("write", [
    lambda s: s.save(APP, V1, {"verstr": V1}, {}),
    lambda s: s.update_metadata(APP, V1, {"note": "x"}),
    lambda s: s.update_note(APP, V1, "x"),
    lambda s: s.save_file(APP, V1, "metadata.yml", "verstr: x\n"),
    lambda s: s.save_file(APP, V1, "output.log", "line"),
    lambda s: s.append_log_entries(APP, V1, "w", [{"type": "metric"}]),
    lambda s: s.append_log_entry(APP, V1, "w", {"type": "metric"}),
    lambda s: s.delete(APP, V1),
], ids=["save", "update_metadata", "update_note", "metadata_file",
        "other_file", "log_batch", "log_entry", "delete"])
def test_each_write_kind_puts_exactly_one_entry(store, sink, write):
    _claimed(store)
    sink.keys.clear()
    write(store)
    assert [e.name for e in _entries(sink)] == [V1]


def test_artifact_upload_puts_one_entry(store, sink, tmp_path):
    _claimed(store)
    sink.keys.clear()
    src = tmp_path / "model.bin"
    src.write_bytes(b"m")
    store.save_artifact_file(APP, V1, str(src))
    assert len(sink.keys) == 1


def test_heartbeat_run_state_puts_none_final_puts_one(store, sink):
    _claimed(store)
    sink.keys.clear()
    beat = {"state": "running", "heartbeat": "t", "exit_code": None}
    store.save_file(APP, V1, "run_state.yml", yaml.dump(beat))
    assert sink.keys == []
    final = dict(beat, state="finished", exit_code=0)
    store.save_file(APP, V1, "run_state.yml", yaml.dump(final))
    assert len(sink.keys) == 1


def test_seq_grows_per_entry(store, sink):
    _claimed(store)
    store.update_note(APP, V1, "x")
    seqs = [e.seq for e in _entries(sink)]
    assert seqs == sorted(seqs) and len(set(seqs)) == 2


def test_other_areas_are_journaled_under_their_area(store, sink):
    store.in_area("code").save(APP, "k", {"verstr": "k"}, {})
    assert [e.area for e in _entries(sink)] == ["code"]
    assert isinstance(store.in_area("code"), JournaledStorage)


def test_failing_put_is_retried(tmp_path):
    sink = RecordingSink(fail=2)
    _claimed(_store(tmp_path, sink, retries=3))
    assert len(sink.keys) == 1 and sink.calls == 3


def test_put_that_still_fails_is_queued_for_the_next_write(tmp_path):
    sink = RecordingSink(fail=3)
    store = _claimed(_store(tmp_path, sink, retries=3))
    assert sink.keys == []
    store.update_note(APP, V1, "x")
    assert len(set(sink.keys)) == 2


def test_queued_entries_flush_on_demand(tmp_path):
    sink = RecordingSink(fail=3)
    store = _claimed(_store(tmp_path, sink, retries=3))
    store.flush_journal()
    assert len(sink.keys) == 1

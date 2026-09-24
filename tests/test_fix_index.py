"""ExperimentIndex: incremental leaderboard rows that match the direct fold."""
import os

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage, get_snapshot_storage
from version_stamp.core.experiment_index import ExperimentIndex
from version_stamp.ui.readers.experiments import direct_rows_and_states

APP = "app"


def _storage(root):
    return get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")


def _make(storage, i, entries_by_writer=None, run_state=None, note=None):
    verstr = f"0.0.1-dev.abc.r{i}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{i:02d}Z", "note": note}
    storage.save(APP, verstr, meta, {})
    for writer, entries in (entries_by_writer or {}).items():
        for entry in entries:
            storage.append_log_entry(APP, verstr, writer, entry)
    if run_state is not None:
        storage.save_file(APP, verstr, "run_state.yml", run_state)
    return verstr


def _metric(ts, **values):
    return {"timestamp": ts, "type": "metrics", "values": values}


def _seed(storage, n=4):
    verstrs = []
    for i in range(n):
        verstrs.append(
            _make(
                storage,
                i,
                {
                    "w0": [
                        {"timestamp": "2026-01-01T00:00:00Z", "type": "create",
                         "note": f"n{i}", "params": {"lr": 0.1 * (i + 1), "opt": "adam"}},
                        _metric("2026-01-01T00:01:00Z", loss=1.0 / (i + 1)),
                    ],
                    "w1": [_metric("2026-01-01T00:02:00Z", acc=0.5 + i / 10)],
                },
                run_state="state: finished\nexit_code: 0\n" if i % 2 else None,
            )
        )
    return verstrs


def _direct(storage):
    return direct_rows_and_states(storage, APP)


@pytest.fixture
def reads(monkeypatch):
    """Every tail read and whole-file read the index makes, as (name, offset)."""
    calls = []
    real_tail = LocalSnapshotStorage.read_file_from
    real_load = LocalSnapshotStorage.load_file

    def tail(self, app_name, verstr, filename, offset):
        calls.append((verstr, filename, offset))
        return real_tail(self, app_name, verstr, filename, offset)

    def load(self, app_name, verstr, filename):
        calls.append((verstr, filename, None))
        return real_load(self, app_name, verstr, filename)

    monkeypatch.setattr(LocalSnapshotStorage, "read_file_from", tail)
    monkeypatch.setattr(LocalSnapshotStorage, "load_file", load)
    return calls


def _index(storage, tmp_path, name="index.sqlite"):
    return ExperimentIndex(storage, APP, cache_path=str(tmp_path / name))


def test_rows_and_run_states_match_the_direct_fold(tmp_path):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    index = _index(storage, tmp_path)
    index.refresh()

    rows, states = _direct(storage)
    assert index.rows() == rows
    assert index.run_states() == states


def test_an_append_reads_only_the_new_bytes(tmp_path, reads):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage)
    index = _index(storage, tmp_path)
    index.refresh()

    log = os.path.join(storage._local._snapshot_dir(APP, verstrs[2]), "log.w0.jsonl")
    before = os.path.getsize(log)
    storage.append_log_entry(APP, verstrs[2], "w0", _metric("2026-01-01T00:09:00Z", loss=0.01))
    reads.clear()
    index.refresh()

    assert reads == [(verstrs[2], "log.w0.jsonl", before)]
    assert index.rows() == _direct(storage)[0]
    assert index.rows()[2]["metrics"]["loss"] == 0.01


def test_a_heartbeat_rereads_only_that_run_state(tmp_path, reads):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage)
    index = _index(storage, tmp_path)
    index.refresh()

    storage.save_file(APP, verstrs[0], "run_state.yml", "state: finished\nexit_code: 3\n")
    reads.clear()
    index.refresh()

    assert reads == [(verstrs[0], "run_state.yml", None)]
    assert index.run_states()[verstrs[0]]["exit_code"] == 3


def test_nothing_changed_reads_nothing(tmp_path, reads):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    index = _index(storage, tmp_path)
    index.refresh()
    reads.clear()
    index.refresh()
    assert reads == []


def test_new_and_deleted_experiments(tmp_path):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage, n=3)
    index = _index(storage, tmp_path)
    index.refresh()

    _make(storage, 9, {"w0": [_metric("2026-01-01T00:05:00Z", loss=0.3)]})
    storage.delete(APP, verstrs[0])
    index.refresh()

    assert index.rows() == _direct(storage)[0]
    assert [r["idx"] for r in index.rows()] == [1, 2, 3]
    assert verstrs[0] not in index.run_states()


def test_a_rewritten_log_is_refolded_from_scratch(tmp_path):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage, n=2)
    index = _index(storage, tmp_path)
    index.refresh()

    log = os.path.join(storage._local._snapshot_dir(APP, verstrs[1]), "log.w0.jsonl")
    with open(log, "w") as f:
        f.write('{"timestamp": "2026-01-01T00:00:01Z", "type": "metrics", "values": {"x": 1}}\n')
    index.refresh()

    assert index.rows() == _direct(storage)[0]
    assert "loss" not in index.rows()[1]["metrics"]


def test_a_partial_trailing_line_is_folded_once_it_completes(tmp_path):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage, n=1)
    index = _index(storage, tmp_path)
    index.refresh()

    log = os.path.join(storage._local._snapshot_dir(APP, verstrs[0]), "log.w0.jsonl")
    line = '{"timestamp": "2026-01-01T00:08:00Z", "type": "metrics", "values": {"loss": 0.2}}\n'
    with open(log, "a") as f:
        f.write(line[:30])
    index.refresh()
    assert index.rows()[0]["metrics"]["loss"] == 1.0

    with open(log, "a") as f:
        f.write(line[30:])
    index.refresh()
    assert index.rows()[0]["metrics"]["loss"] == 0.2
    assert index.rows() == _direct(storage)[0]


def test_a_note_update_rereads_metadata_only(tmp_path, reads):
    storage = _storage(tmp_path / "repo")
    verstrs = _seed(storage, n=2)
    index = _index(storage, tmp_path)
    index.refresh()

    storage.update_note(APP, verstrs[1], "renamed")
    reads.clear()
    index.refresh()

    assert reads == [(verstrs[1], "metadata.yml", None)]
    assert index.rows()[1]["note"] == "renamed"


def test_a_second_index_over_the_same_cache_reads_no_logs(tmp_path, reads):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    first = _index(storage, tmp_path)
    first.refresh()

    reads.clear()
    second = _index(storage, tmp_path)
    second.refresh()

    assert reads == []
    assert second.rows() == first.rows()
    assert second.run_states() == first.run_states()


def test_a_corrupt_cache_is_rebuilt(tmp_path):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    (tmp_path / "index.sqlite").write_bytes(b"this is not a database" * 100)

    index = _index(storage, tmp_path)
    index.refresh()
    assert index.rows() == _direct(storage)[0]


def test_an_unusable_cache_path_still_serves_rows(tmp_path):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    index = ExperimentIndex(storage, APP, cache_path=str(tmp_path / "missing" / "x.sqlite"))
    index.refresh()
    assert index.rows() == _direct(storage)[0]


def test_an_in_memory_index_needs_no_cache_path(tmp_path):
    storage = _storage(tmp_path / "repo")
    _seed(storage)
    index = ExperimentIndex(storage, APP)
    index.refresh()
    assert index.rows() == _direct(storage)[0]


def test_rows_are_fresh_copies(tmp_path):
    storage = _storage(tmp_path / "repo")
    _seed(storage, n=1)
    index = _index(storage, tmp_path)
    index.refresh()
    index.rows()[0]["status"] = "mutated"
    assert "status" not in index.rows()[0]


def test_legacy_log_yml_and_segments_fold_like_the_reader(tmp_path):
    storage = _storage(tmp_path / "repo")
    verstr = _make(storage, 1, {"w0": [_metric("2026-01-01T00:03:00Z", loss=0.3)]})
    folder = storage._local._snapshot_dir(APP, verstr)
    with open(os.path.join(folder, "log.yml"), "w") as f:
        f.write("- {timestamp: '2026-01-01T00:04:00Z', type: metrics, values: {loss: 0.9}}\n")
    with open(os.path.join(folder, "log.w0@000001.jsonl"), "w") as f:
        f.write('{"timestamp": "2026-01-01T00:05:00Z", "type": "metrics", "values": {"acc": 1}}\n')
    index = _index(storage, tmp_path)
    index.refresh()
    assert index.rows() == _direct(storage)[0]


def test_cached_storage_with_a_remote_folds_like_the_reader(tmp_path, monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3").create_bucket(Bucket="vmn-bucket")
        storage = get_snapshot_storage(
            "local", vmn_root_path=str(tmp_path / "repo"), bucket="vmn-bucket",
            prefix="exps", subdir="experiments",
        )
        verstrs = _seed(storage, n=2)
        storage.sync_log_to_remote(APP, verstrs[0], "w0")
        index = _index(storage, tmp_path)
        index.refresh()
        assert index.rows() == _direct(storage)[0]

        storage.append_log_entry(APP, verstrs[0], "w0", _metric("2026-01-01T00:09:00Z", loss=0.05))
        index.refresh()
        assert index.rows() == _direct(storage)[0]

"""LocalSnapshotStorage.list_files: a record directory whose signature (mtime,
inode) has not moved since a listing old enough to trust is re-listed by
stat-ing the files it held — no directory scan — and every other one is
scanned. Opening a directory costs ~10x a stat, and a full listing is what
every refresh of a large index pays."""
import os
import time

import pytest

from version_stamp.cli.snapshot import LocalSnapshotStorage

APP = "app"
HOUR_NS = 3600 * 10**9


@pytest.fixture
def storage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    for i in range(3):
        verstr = f"0.0.1-dev.abc.r{i}"
        st.save(APP, verstr, {"verstr": verstr, "timestamp": f"t{i}"}, {})
        st.append_log_entry(APP, verstr, "w", {"type": "metrics", "values": {"i": i}})
    return st


def _dir(storage, i):
    return storage.plain_record_dir(APP, f"0.0.1-dev.abc.r{i}")


def _age(storage):
    """Every record directory's mtime an hour back: long settled."""
    for i in range(3):
        _set_mtime(_dir(storage, i), time.time_ns() - HOUR_NS)


def _set_mtime(path, mtime_ns):
    os.utime(path, ns=(mtime_ns, mtime_ns))


@pytest.fixture
def scans(monkeypatch):
    calls = []
    real = os.scandir
    monkeypatch.setattr(os, "scandir", lambda path=".": calls.append(path) or real(path))
    return calls


def test_settled_records_are_listed_again_without_scanning_them(storage, scans):
    _age(storage)
    first = storage.list_files(APP)
    scans.clear()

    assert storage.list_files(APP) == first
    assert len(scans) == 1  # the base directory only


def test_an_in_place_append_to_a_settled_record_still_shows(storage):
    _age(storage)
    storage.list_files(APP)
    log = os.path.join(_dir(storage, 1), "log.w.jsonl")
    with open(log, "a") as f:
        f.write('{"type": "metrics", "values": {"i": 9}}\n')

    listed = storage.list_files(APP)["0.0.1-dev.abc.r1"]["log.w.jsonl"]

    assert listed[0] == os.path.getsize(log)


def test_a_record_that_changed_is_scanned_again(storage):
    _age(storage)
    storage.list_files(APP)
    storage.save_file(APP, "0.0.1-dev.abc.r2", "run_state.yml", "state: running\n")

    assert "run_state.yml" in storage.list_files(APP)["0.0.1-dev.abc.r2"]


def test_a_listing_too_close_to_the_directory_mtime_is_not_trusted(storage):
    # A coarse-mtime filesystem (whole seconds) can give a later change the
    # same timestamp.
    path = _dir(storage, 0)
    before = time.time_ns() // 10**9 * 10**9
    _set_mtime(path, before)
    storage.list_files(APP)
    storage.save_file(APP, "0.0.1-dev.abc.r0", "run_state.yml", "state: running\n")
    _set_mtime(path, before)

    assert "run_state.yml" in storage.list_files(APP)["0.0.1-dev.abc.r0"]


def test_a_file_gone_behind_an_unchanged_signature_is_scanned_again(storage):
    _age(storage)
    path = _dir(storage, 1)
    mtime = os.stat(path).st_mtime_ns
    storage.list_files(APP)
    os.remove(os.path.join(path, "log.w.jsonl"))
    _set_mtime(path, mtime)

    assert "log.w.jsonl" not in storage.list_files(APP)["0.0.1-dev.abc.r1"]


def test_a_removed_record_leaves_the_listing(storage):
    _age(storage)
    storage.list_files(APP)
    storage.delete(APP, "0.0.1-dev.abc.r2")

    assert sorted(storage.list_files(APP)) == ["0.0.1-dev.abc.r0", "0.0.1-dev.abc.r1"]


def test_a_fine_grained_mtime_is_trusted_at_once(storage, scans):
    # Sub-second mtimes: a later change always moves the signature, so a
    # just-written record need not settle before its listing is reused.
    for i in range(3):
        _set_mtime(_dir(storage, i), time.time_ns() - 10**6 - 12345)
    first = storage.list_files(APP)
    scans.clear()

    assert storage.list_files(APP) == first
    assert len(scans) == 1  # the base directory only

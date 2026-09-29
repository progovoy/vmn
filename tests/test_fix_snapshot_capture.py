"""`vmn snapshot create`: cap-skipped untracked paths and verstr collisions."""
import io
import os
import tarfile

import pytest

from version_stamp.core import logging as vmn_logging
from version_stamp.snapshot import capture as snapshot_capture
from version_stamp.snapshot.stores import local_snapshot_stores
from helpers import _bootstrap, _snapshot

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _write(path, nbytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * nbytes)


def _members(tarball):
    with tarfile.open(mode="r:gz", fileobj=io.BytesIO(tarball)) as tar:
        return sorted(m.name for m in tar.getmembers())


def _stamped(app_layout):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")


def _records(app_layout):
    return local_snapshot_stores(app_layout.repo_path).records


def _dirty(app_layout, content):
    with open(os.path.join(app_layout.repo_path, "tracked.txt"), "w") as f:
        f.write(content)


def test_skipped_untracked_recorded_in_snapshot_metadata(app_layout, monkeypatch):
    _stamped(app_layout)
    _dirty(app_layout, "dirty")
    _write(os.path.join(app_layout.repo_path, "weights.bin"), 2 * MB)
    _write(os.path.join(app_layout.repo_path, "notes.txt"), 5)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    assert _snapshot(app_layout.app_name) == 0

    meta = _records(app_layout).list_snapshots(app_layout.app_name)[-1]
    assert meta["untracked_skipped"] == ["weights.bin"]
    _, patches = _records(app_layout).load(app_layout.app_name, meta["verstr"])
    assert _members(patches["untracked_files"]) == ["notes.txt"]


def _force_hashes(monkeypatch, hashes):
    """Give each distinct working-tree state the next hash in *hashes*."""
    remaining = iter(hashes)
    by_state = {}

    def fake(patches):
        state = patches.get("working_tree")
        if state not in by_state:
            by_state[state] = next(remaining)
        return by_state[state]

    monkeypatch.setattr(snapshot_capture, "_compute_diff_hash", fake)


def test_colliding_diff_hash_extends_instead_of_overwriting(app_layout, monkeypatch):
    _stamped(app_layout)
    first_hash = "abcdef1" + "0" * 57
    second_hash = "abcdef1" + "1" * 57
    _force_hashes(monkeypatch, [first_hash, second_hash])

    _dirty(app_layout, "state one")
    assert _snapshot(app_layout.app_name, note="first") == 0
    _dirty(app_layout, "state two")
    assert _snapshot(app_layout.app_name, note="second") == 0

    records = _records(app_layout)
    metas = {m["note"]: m for m in records.list_snapshots(app_layout.app_name)}
    assert set(metas) == {"first", "second"}
    assert metas["first"]["verstr"].endswith(".abcdef1")
    assert metas["second"]["verstr"].endswith(".abcdef111111")
    assert metas["first"]["diff_hash"] == first_hash
    assert metas["second"]["diff_hash"] == second_hash

    _, first_patches = records.load(app_layout.app_name, metas["first"]["verstr"])
    assert "state one" in first_patches["working_tree"]


def test_same_diff_hash_stays_idempotent(app_layout, monkeypatch):
    _stamped(app_layout)
    same = "abcdef1" + "2" * 57
    _force_hashes(monkeypatch, [same, same])

    _dirty(app_layout, "same state")
    assert _snapshot(app_layout.app_name) == 0
    assert _snapshot(app_layout.app_name) == 0

    metas = _records(app_layout).list_snapshots(app_layout.app_name)
    assert len(metas) == 1
    assert metas[0]["verstr"].endswith(".abcdef1")

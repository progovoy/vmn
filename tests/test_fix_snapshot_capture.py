"""Snapshot capture: untracked-size caps and verstr identity collisions."""
import io
import os
import subprocess
import tarfile

import pytest

from version_stamp.cli import snapshot as snap
from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.core import logging as vmn_logging
from version_stamp.core.version_math import deserialize_vmn_version
from helpers import _init_app, _run_vmn_init, _snapshot, _stamp_app

MB = 1024 * 1024


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _git_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return str(tmp_path)


def _write(path, nbytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * nbytes)


def _members(tarball):
    with tarfile.open(mode="r:gz", fileobj=io.BytesIO(tarball)) as tar:
        return sorted(m.name for m in tar.getmembers())


# ---------------------------------------------------------------------------
# untracked caps
# ---------------------------------------------------------------------------


def test_default_untracked_caps(monkeypatch):
    monkeypatch.delenv("VMN_SNAPSHOT_MAX_FILE_MB", raising=False)
    monkeypatch.delenv("VMN_SNAPSHOT_MAX_TOTAL_MB", raising=False)
    assert snap._untracked_caps() == (50 * MB, 200 * MB)


def test_untracked_file_over_per_file_cap_is_skipped(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    _write(os.path.join(repo, "small.txt"), 10)
    _write(os.path.join(repo, "ckpt", "big.bin"), 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    tarball, skipped = snap._collect_untracked_tarball(repo)

    assert _members(tarball) == ["small.txt"]
    assert skipped == ["ckpt/big.bin"]


def test_untracked_total_cap_stops_adding(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    for name in ("a.bin", "b.bin", "c.bin"):
        _write(os.path.join(repo, name), 400 * 1024)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_TOTAL_MB", "1")

    tarball, skipped = snap._collect_untracked_tarball(repo)

    assert _members(tarball) == ["a.bin", "b.bin"]
    assert skipped == ["c.bin"]


def test_all_untracked_skipped_yields_no_tarball(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    _write(os.path.join(repo, "big.bin"), 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    tarball, skipped = snap._collect_untracked_tarball(repo)

    assert tarball is None
    assert skipped == ["big.bin"]


def _stamped(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")


def _storage(app_layout):
    return LocalSnapshotStorage(app_layout.repo_path)


def _dirty(app_layout, content):
    with open(os.path.join(app_layout.repo_path, "tracked.txt"), "w") as f:
        f.write(content)


def _latest_meta(app_layout):
    storage = _storage(app_layout)
    metas = storage.list_snapshots(app_layout.app_name)
    return metas[-1]


def test_skipped_untracked_recorded_in_snapshot_metadata(app_layout, monkeypatch):
    _stamped(app_layout)
    _dirty(app_layout, "dirty")
    _write(os.path.join(app_layout.repo_path, "weights.bin"), 2 * MB)
    _write(os.path.join(app_layout.repo_path, "notes.txt"), 5)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    assert _snapshot(app_layout.app_name) == 0

    meta = _latest_meta(app_layout)
    assert meta["untracked_skipped"] == ["weights.bin"]
    _, patches = _storage(app_layout).load(app_layout.app_name, meta["verstr"])
    assert _members(patches["untracked_files"]) == ["notes.txt"]


def test_no_skipped_key_when_nothing_skipped(app_layout):
    _stamped(app_layout)
    _dirty(app_layout, "dirty")

    assert _snapshot(app_layout.app_name) == 0

    assert "untracked_skipped" not in _latest_meta(app_layout)


# ---------------------------------------------------------------------------
# verstr identity
# ---------------------------------------------------------------------------


def test_full_diff_hash_recorded_in_metadata(app_layout):
    _stamped(app_layout)
    _dirty(app_layout, "dirty")

    assert _snapshot(app_layout.app_name) == 0

    meta = _latest_meta(app_layout)
    assert len(meta["diff_hash"]) == 64
    assert meta["verstr"].endswith("." + meta["diff_hash"][:7])


def test_extended_dev_verstr_parses():
    props = deserialize_vmn_version("0.0.1-dev.abcdef1.abcdef111111")
    assert props.dev_commit == "abcdef1"
    assert props.dev_diff_hash == "abcdef111111"

    run = deserialize_vmn_version("0.0.1-dev.abcdef1.abcdef111111.r3")
    assert run.dev_diff_hash == "abcdef111111"
    assert run.dev_run == 3


def _force_hashes(monkeypatch, hashes):
    """Give each distinct working-tree state the next hash in *hashes*."""
    remaining = iter(hashes)
    by_state = {}

    def fake(patches):
        state = patches.get("working_tree")
        if state not in by_state:
            by_state[state] = next(remaining)
        return by_state[state]

    monkeypatch.setattr(snap, "_compute_diff_hash", fake)


def test_colliding_diff_hash_extends_instead_of_overwriting(app_layout, monkeypatch):
    _stamped(app_layout)
    first_hash = "abcdef1" + "0" * 57
    second_hash = "abcdef1" + "1" * 57
    _force_hashes(monkeypatch, [first_hash, second_hash])

    _dirty(app_layout, "state one")
    assert _snapshot(app_layout.app_name, note="first") == 0
    _dirty(app_layout, "state two")
    assert _snapshot(app_layout.app_name, note="second") == 0

    metas = {m["note"]: m for m in _storage(app_layout).list_snapshots(app_layout.app_name)}
    assert set(metas) == {"first", "second"}
    assert metas["first"]["verstr"].endswith(".abcdef1")
    assert metas["second"]["verstr"].endswith(".abcdef111111")
    assert metas["first"]["diff_hash"] == first_hash
    assert metas["second"]["diff_hash"] == second_hash

    _, first_patches = _storage(app_layout).load(
        app_layout.app_name, metas["first"]["verstr"]
    )
    assert "state one" in first_patches["working_tree"]


def test_same_diff_hash_stays_idempotent(app_layout, monkeypatch):
    _stamped(app_layout)
    same = "abcdef1" + "2" * 57
    _force_hashes(monkeypatch, [same, same])

    _dirty(app_layout, "same state")
    assert _snapshot(app_layout.app_name) == 0
    assert _snapshot(app_layout.app_name) == 0

    verstrs = [m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)]
    assert len(verstrs) == 1
    assert verstrs[0].endswith(".abcdef1")


def test_legacy_snapshot_without_diff_hash_is_not_overwritten(app_layout, monkeypatch):
    _stamped(app_layout)
    forced = "abcdef1" + "3" * 57
    _force_hashes(monkeypatch, [forced])
    storage = _storage(app_layout)

    # A legacy record (no diff_hash) occupying the verstr the next create computes.
    _dirty(app_layout, "new state")
    legacy_verstr = f"0.0.1-dev.{_head(app_layout)[:7]}.abcdef1"
    legacy_meta = {
        "verstr": legacy_verstr,
        "timestamp": "2020-01-01T00:00:00Z",
        "note": "legacy",
    }
    storage.save(app_layout.app_name, legacy_verstr, legacy_meta, {})

    assert _snapshot(app_layout.app_name, note="fresh") == 0

    notes = {m["verstr"]: m["note"] for m in storage.list_snapshots(app_layout.app_name)}
    assert notes[legacy_verstr] == "legacy"
    assert "fresh" in notes.values()


def _head(app_layout):
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        cwd=app_layout.repo_path,
    ).stdout.strip()


@pytest.mark.parametrize("hash_len", [7, 12])
def test_compute_verstr_hash_length(hash_len):
    patches = {"working_tree": "diff --git a/x b/x\n"}
    full = snap._compute_diff_hash(patches)
    verstr = snap._compute_verstr("1.2.3", "a" * 40, patches, hash_len=hash_len)
    assert verstr == f"1.2.3-dev.aaaaaaa.{full[:hash_len]}"


def test_clean_tree_diff_hash_is_zeroed():
    assert snap._compute_diff_hash({}) is None
    assert snap._compute_verstr("1.2.3", "b" * 40, {}) == "1.2.3-dev.bbbbbbb.0000000"

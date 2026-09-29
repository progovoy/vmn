"""Dev-version capture: untracked-size caps, gitignore handling and the diff
hash / verstr identity, driven through `vmn-exp create`."""
import io
import os
import subprocess
import tarfile

import pytest

from vmn_exp import snapshot as snap
import version_stamp.devversion.untracked as dv_untracked
from version_stamp.core import logging as vmn_logging
from helpers import (
    DEV_VERSION_RE,
    _bootstrap,
    _experiment,
    _show,
    _storage,
    extract_dev_verstr,
)

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


def _write_text(app_layout, name, content):
    path = os.path.join(app_layout.repo_path, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


def _members(tarball):
    with tarfile.open(mode="r:gz", fileobj=io.BytesIO(tarball)) as tar:
        return sorted(m.name for m in tar.getmembers())


def _stamped_dirty(app_layout):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")
    _write_text(app_layout, "tracked.txt", "dirty")


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _experiment(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _record(app_layout, verstr):
    return _storage(app_layout).load(app_layout.app_name, verstr)


def _code_verstr(verstr):
    """The code identity of a run id: its ``.rN`` run suffix dropped."""
    head, _, tail = verstr.rpartition(".")
    return head if tail.startswith("r") and tail[1:].isdigit() else verstr


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

    tarball, skipped = dv_untracked._collect_untracked_tarball(repo)

    assert _members(tarball) == ["small.txt"]
    assert skipped == ["ckpt/big.bin"]


def test_untracked_total_cap_stops_adding(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    for name in ("a.bin", "b.bin", "c.bin"):
        _write(os.path.join(repo, name), 400 * 1024)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_TOTAL_MB", "1")

    tarball, skipped = dv_untracked._collect_untracked_tarball(repo)

    assert _members(tarball) == ["a.bin", "b.bin"]
    assert skipped == ["c.bin"]


def test_all_untracked_skipped_yields_no_tarball(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    _write(os.path.join(repo, "big.bin"), 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    tarball, skipped = dv_untracked._collect_untracked_tarball(repo)

    assert tarball is None
    assert skipped == ["big.bin"]


def test_skipped_untracked_recorded_in_metadata(app_layout, capfd, monkeypatch):
    _stamped_dirty(app_layout)
    _write(os.path.join(app_layout.repo_path, "weights.bin"), 2 * MB)
    _write(os.path.join(app_layout.repo_path, "notes.txt"), 5)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")

    meta, patches = _record(app_layout, _create(app_layout, capfd))

    assert meta["untracked_skipped"] == ["weights.bin"]
    assert _members(patches["untracked_files"]) == ["notes.txt"]


def test_no_skipped_key_when_nothing_skipped(app_layout, capfd):
    _stamped_dirty(app_layout)

    meta, _ = _record(app_layout, _create(app_layout, capfd))

    assert "untracked_skipped" not in meta


def test_gitignored_files_are_not_captured(app_layout, capfd):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", ".gitignore", "*.log\n.env\nsecrets/\n")
    _write_text(app_layout, ".env", "SECRET=xyz")
    _write_text(app_layout, "debug.log", "log data")
    _write_text(app_layout, os.path.join("secrets", "key.txt"), "private")
    _write_text(app_layout, "visible.py", "visible")

    _, patches = _record(app_layout, _create(app_layout, capfd))

    assert _members(patches["untracked_files"]) == ["visible.py"]


# ---------------------------------------------------------------------------
# verstr identity
# ---------------------------------------------------------------------------


def test_full_diff_hash_recorded_in_metadata(app_layout, capfd):
    _stamped_dirty(app_layout)

    verstr = _create(app_layout, capfd)
    meta, _ = _record(app_layout, verstr)

    assert len(meta["diff_hash"]) == 64
    assert verstr.endswith("." + meta["diff_hash"][:7])


def test_show_dev_matches_the_recorded_code_verstr(app_layout, capfd):
    """`show --dev` and `vmn-exp create` agree on the dev verstr even with
    untracked files present, so `vmn goto` finds the record."""
    _stamped_dirty(app_layout)
    _write_text(app_layout, "untracked_note.txt", "some untracked content\n")

    capfd.readouterr()
    assert _show(app_layout.app_name, dev=True) == 0
    show_verstr = capfd.readouterr().out.strip()
    assert DEV_VERSION_RE.match(show_verstr), show_verstr

    assert _code_verstr(_create(app_layout, capfd)) == show_verstr


def test_untracked_hash_stable_across_touch(app_layout, capfd):
    """The diff hash depends on untracked *content*, not mtime."""
    _stamped_dirty(app_layout)
    untracked = _write_text(app_layout, "untracked_note.txt", "some untracked content\n")
    first = _code_verstr(_create(app_layout, capfd))

    st = os.stat(untracked)
    os.utime(untracked, ns=(st.st_atime_ns + 10**9, st.st_mtime_ns + 10**9))
    assert _code_verstr(_create(app_layout, capfd)) == first

    _write_text(app_layout, "untracked_note.txt", "completely different content\n")
    assert _code_verstr(_create(app_layout, capfd)) != first


def test_untracked_hash_cache_hit(app_layout):
    """`_hash_untracked_content` caches by (path, size, mtime)."""
    _bootstrap(app_layout)
    f_path = _write_text(app_layout, "cached.txt", "A")
    h1 = dv_untracked._hash_untracked_content(app_layout.repo_path)
    assert h1 is not None

    # Same-length content with the original stat restored: the cache key matches.
    st = os.stat(f_path)
    _write_text(app_layout, "cached.txt", "B")
    os.utime(f_path, ns=(st.st_atime_ns, st.st_mtime_ns))

    assert dv_untracked._hash_untracked_content(app_layout.repo_path) == h1


@pytest.mark.parametrize("hash_len", [7, 12])
def test_compute_verstr_hash_length(hash_len):
    patches = {"working_tree": "diff --git a/x b/x\n"}
    full = snap._compute_diff_hash(patches)
    verstr = snap._compute_verstr("1.2.3", "a" * 40, patches, hash_len=hash_len)
    assert verstr == f"1.2.3-dev.aaaaaaa.{full[:hash_len]}"


def test_clean_tree_diff_hash_is_zeroed():
    assert snap._compute_diff_hash({}) is None
    assert snap._compute_verstr("1.2.3", "b" * 40, {}) == "1.2.3-dev.bbbbbbb.0000000"

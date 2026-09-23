"""Materializing snapshots for export/diff: local-first, no untracked leakage."""
import os
import subprocess

import pytest
import yaml

from version_stamp.cli import snapshot as snap
from version_stamp.core import logging as vmn_logging
from version_stamp.cli.snapshot import LocalSnapshotStorage
from version_stamp.ui.readers import snapshots as snap_reader
from helpers import _init_app, _run_vmn_init, _snapshot, _stamp_app, extract_dev_verstr

UNREACHABLE_REMOTE = "https://127.0.0.1:9/no/such/repo.git"


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _stamped_dirty_snapshot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "tracked.txt"), "w") as f:
        f.write("dirty tracked")
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _rewrite_meta(app_layout, verstr, **updates):
    storage = LocalSnapshotStorage(app_layout.repo_path)
    path = os.path.join(storage._snapshot_dir(app_layout.app_name, verstr), "metadata.yml")
    with open(path) as f:
        meta = yaml.safe_load(f)
    meta.update(updates)
    with open(path, "w") as f:
        yaml.dump(meta, f)


def test_export_uses_local_commit_when_remote_is_unreachable(app_layout, capfd, tmp_path):
    verstr = _stamped_dirty_snapshot(app_layout, capfd)
    _rewrite_meta(app_layout, verstr, remote=UNREACHABLE_REMOTE)
    out = str(tmp_path / "export")

    assert _snapshot(app_layout.app_name, action="export", version=verstr, output=out) == 0

    with open(os.path.join(out, "tracked.txt")) as f:
        assert f.read() == "dirty tracked"


def test_local_materialize_never_touches_the_network(app_layout, capfd, tmp_path, monkeypatch):
    verstr = _stamped_dirty_snapshot(app_layout, capfd)
    _rewrite_meta(app_layout, verstr, remote=UNREACHABLE_REMOTE)
    real_run = subprocess.run
    network = []

    def spy(cmd, *args, **kwargs):
        if isinstance(cmd, list) and UNREACHABLE_REMOTE in cmd:
            network.append(cmd)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(snap.subprocess, "run", spy)
    out = str(tmp_path / "export")
    assert _snapshot(app_layout.app_name, action="export", version=verstr, output=out) == 0
    assert network == []


def test_export_does_not_copy_live_untracked_files(app_layout, capfd, tmp_path):
    verstr = _stamped_dirty_snapshot(app_layout, capfd)
    # Created after the snapshot: not part of it, must not leak into the export.
    with open(os.path.join(app_layout.repo_path, "leak.txt"), "w") as f:
        f.write("not in the snapshot")
    out = str(tmp_path / "export")

    assert _snapshot(app_layout.app_name, action="export", version=verstr, output=out) == 0

    assert not os.path.exists(os.path.join(out, "leak.txt"))


def test_clone_timeout_is_an_error_not_a_hang(tmp_path, monkeypatch):
    def timeout(cmd, *args, **kwargs):
        assert kwargs.get("timeout"), f"no timeout on {cmd}"
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(snap.subprocess, "run", timeout)

    assert snap._shallow_clone_at(str(tmp_path / "d"), UNREACHABLE_REMOTE, "a" * 40) == 1


def test_snapshot_detail_does_not_read_the_untracked_tarball(app_layout, capfd, monkeypatch):
    verstr = _stamped_dirty_snapshot(app_layout, capfd)
    read = []
    real = snap._read_patches_from_dir
    monkeypatch.setattr(
        snap, "_read_patches_from_dir", lambda d: read.append(d) or real(d)
    )

    detail, err = snap_reader.get_snapshot(app_layout.repo_path, app_layout.app_name, verstr)

    assert err is None
    assert read == []
    assert detail["patches"] == {
        "working_tree": True,
        "local_commits": False,
        "untracked_files": False,
    }
    assert detail["metadata"]["verstr"] == verstr

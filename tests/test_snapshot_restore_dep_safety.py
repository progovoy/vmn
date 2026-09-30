"""`vmn snapshot restore` and deps: untracked files a dep reset would delete
are guarded like the app's, and a dep's unpushed commits restore on top of
its upstream base."""
import os
import shutil
import subprocess

from helpers import _snapshot, extract_dev_verstr
from test_snapshot_restore_integrity import with_dep  # noqa: F401 (fixture)

MB = 1024 * 1024


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _read(path):
    with open(path) as f:
        return f.read()


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _restore(app_layout, capfd, verstr, force=False):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="restore", version=verstr, force=force)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


def _snapshot_then_add_big_dep_file(app_layout, capfd, dep, monkeypatch):
    work = os.path.join(app_layout.repo_path, "work.txt")
    _write(work, "snapshot\n")
    verstr = _create(app_layout, capfd)
    _write(work, "unsaved\n")
    big = os.path.join(dep, "weights.bin")
    with open(big, "wb") as f:
        f.write(b"x" * 2 * MB)
    monkeypatch.setenv("VMN_SNAPSHOT_MAX_FILE_MB", "1")
    return verstr, work, big


def test_restore_refuses_when_a_dep_reset_would_drop_untracked_files(
    app_layout, capfd, with_dep, monkeypatch
):
    verstr, work, big = _snapshot_then_add_big_dep_file(
        app_layout, capfd, with_dep, monkeypatch
    )

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 1
    assert "weights.bin" in out and "--force" in out
    assert os.path.getsize(big) == 2 * MB
    assert _read(work) == "unsaved\n"


def test_restore_force_proceeds_despite_a_dep_dropping_untracked_files(
    app_layout, capfd, with_dep, monkeypatch
):
    verstr, work, big = _snapshot_then_add_big_dep_file(
        app_layout, capfd, with_dep, monkeypatch
    )

    ret, out = _restore(app_layout, capfd, verstr, force=True)

    assert ret == 0, out
    assert _read(work) == "snapshot\n"
    assert not os.path.exists(big)


def _fresh_clone(path):
    remote = _git(path, "remote", "get-url", "origin")
    shutil.rmtree(path)
    subprocess.run(["git", "clone", "-q", remote, path], check=True)


def test_restore_replays_a_deps_unpushed_commit_on_its_upstream(
    app_layout, capfd, with_dep
):
    app_layout.write_file_commit_and_push("dep1", "pushed.txt", "pushed\n")
    app_layout.write_file_commit_and_push("dep1", "local.txt", "local\n", push=False)
    dep_file = os.path.join(with_dep, "a", "b", "c.txt")
    _write(dep_file, "SNAPSHOT\n")
    _write(os.path.join(app_layout.repo_path, "work.txt"), "snapshot\n")
    verstr = _create(app_layout, capfd)
    upstream = _git(with_dep, "rev-parse", "@{upstream}")
    _fresh_clone(with_dep)

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 0, out
    assert _read(os.path.join(with_dep, "pushed.txt")) == "pushed\n"
    assert _read(os.path.join(with_dep, "local.txt")) == "local\n"
    assert _read(dep_file) == "SNAPSHOT\n"
    assert _git(with_dep, "rev-parse", "HEAD~1") == upstream

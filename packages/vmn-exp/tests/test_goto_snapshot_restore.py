"""`vmn goto` of a snapshot verstr restores it. vmn resolves dev versions
through vmn-exp's dev-version loader (the `vmn.plugins` entry point), so this
lives in the vmn-exp suite (moved from the core suite's test_snapshot_restore.py,
helpers copied from there)."""
import os
import subprocess

import pytest

from exp_helpers import _bootstrap, _goto, _snapshot, extract_dev_verstr


def _path(app_layout, name):
    return os.path.join(app_layout.repo_path, name)


def _read(app_layout, name):
    with open(_path(app_layout, name)) as f:
        return f.read()


def _write(app_layout, name, content):
    with open(_path(app_layout, name), "w") as f:
        f.write(content)


def _snapshot_of(app_layout, capfd, content, name="work.txt"):
    """Commit *name*, dirty it with *content* and snapshot it; the verstr."""
    if not os.path.exists(_path(app_layout, name)):
        app_layout.write_file_commit_and_push("test_repo_0", name, "committed")
    _write(app_layout, name, content)
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _discard_changes(app_layout):
    subprocess.run(["git", "checkout", "."], cwd=app_layout.repo_path, check=True)
    subprocess.run(["git", "clean", "-fdq"], cwd=app_layout.repo_path, check=True)


@pytest.fixture
def stamped(app_layout):
    _bootstrap(app_layout)
    return app_layout


def test_goto_restores_a_snapshot(stamped, capfd):
    _write(stamped, "extra.txt", "untracked in snapshot")
    verstr = _snapshot_of(stamped, capfd, "goto state")
    _discard_changes(stamped)

    assert _goto(stamped.app_name, version=verstr) == 0

    assert _read(stamped, "work.txt") == "goto state"
    assert _read(stamped, "extra.txt") == "untracked in snapshot"

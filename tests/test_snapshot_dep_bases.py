"""Every dep's position is part of a snapshot: a clean dep that moved past its
stamp commit is recorded (``dep_base_commits``), restored there, and two
states differing only in where a dep sits get different verstrs."""
import os
import subprocess

import yaml

from helpers import _snapshot
from test_snapshot_restore_integrity import with_dep  # noqa: F401 (fixture)

DEP = "../dep1"


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


def _create(app_layout, capfd):
    capfd.readouterr()
    assert _snapshot(app_layout.app_name) == 0
    # The last stdout line: extract_dev_verstr only knows 7-hex diff hashes.
    verstr = capfd.readouterr().out.strip().splitlines()[-1]
    assert "-dev." in verstr
    return verstr


def _restore(app_layout, capfd, verstr):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="restore", version=verstr)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


def _meta(app_layout, verstr):
    path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "snapshots", verstr,
        "metadata.yml",
    )
    with open(path) as f:
        return yaml.safe_load(f)


def test_restore_puts_a_clean_moved_dep_at_its_recorded_head(
    app_layout, capfd, with_dep
):
    app_layout.write_file_commit_and_push("dep1", "moved.txt", "moved\n")
    moved = _git(with_dep, "rev-parse", "HEAD")
    _write(os.path.join(app_layout.repo_path, "work.txt"), "snapshot\n")
    verstr = _create(app_layout, capfd)
    assert _meta(app_layout, verstr)["dep_base_commits"][DEP] == moved
    _git(with_dep, "checkout", "-q", "--detach", "HEAD~1")

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 0, out
    assert _git(with_dep, "rev-parse", "HEAD") == moved


def test_same_diff_with_a_dep_elsewhere_gets_a_new_verstr(app_layout, capfd, with_dep):
    _write(os.path.join(app_layout.repo_path, "work.txt"), "snapshot\n")
    at_stamp = _create(app_layout, capfd)
    app_layout.write_file_commit_and_push("dep1", "moved.txt", "moved\n")

    moved = _create(app_layout, capfd)

    assert moved != at_stamp
    assert moved.startswith(at_stamp)
    assert _create(app_layout, capfd) == moved

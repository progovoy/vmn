"""`vmn snapshot restore` puts the whole recorded tree back or fails loudly:
identity-less repos, a missing base commit, and deps (moved, dirty, broken)."""
import os
import subprocess

import pytest
import yaml

from helpers import _bootstrap, _init_app, _run_vmn_init, _snapshot, _stamp_app
from helpers import extract_dev_verstr

_IDENTITY_ENV = (
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "EMAIL",
)


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


def _restore(app_layout, capfd, verstr):
    capfd.readouterr()
    ret = _snapshot(app_layout.app_name, action="restore", version=verstr)
    captured = capfd.readouterr()
    return ret, captured.out + captured.err


def _record_meta_path(app_layout, verstr):
    return os.path.join(
        app_layout.repo_path, ".vmn", "store", "snapshots", app_layout.app_name, verstr,
        "metadata.yml",
    )


def _set_base_commit(app_layout, verstr, base_commit):
    meta_path = _record_meta_path(app_layout, verstr)
    with open(meta_path) as f:
        meta = yaml.safe_load(f)
    meta["base_commit"] = base_commit
    with open(meta_path, "w") as f:
        yaml.safe_dump(meta, f)


def test_restore_applies_local_commits_without_a_committer_identity(
    app_layout, capfd, tmp_path, monkeypatch
):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "local.txt", "local\n", push=False)
    work = os.path.join(app_layout.repo_path, "work.txt")
    _write(work, "dirty\n")
    verstr = _create(app_layout, capfd)
    base = _git(app_layout.repo_path, "rev-parse", "HEAD~1")
    _set_base_commit(app_layout, verstr, base)
    _git(app_layout.repo_path, "reset", "-q", "--hard", base)

    home = tmp_path / "empty_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in _IDENTITY_ENV:
        monkeypatch.delenv(name, raising=False)
    _git(app_layout.repo_path, "config", "--unset", "user.name")
    _git(app_layout.repo_path, "config", "--unset", "user.email")
    _git(app_layout.repo_path, "config", "user.useConfigOnly", "true")

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 0, out
    assert _read(os.path.join(app_layout.repo_path, "local.txt")) == "local\n"
    assert _read(work) == "dirty\n"
    assert not os.path.exists(os.path.join(app_layout.repo_path, ".git", "rebase-apply"))


def test_restore_with_a_missing_base_commit_leaves_the_tree_untouched(app_layout, capfd):
    _bootstrap(app_layout)
    work = os.path.join(app_layout.repo_path, "work.txt")
    _write(work, "snapshot\n")
    verstr = _create(app_layout, capfd)
    _set_base_commit(app_layout, verstr, "0123456789abcdef0123456789abcdef01234567")
    _write(work, "unsaved\n")
    head = _git(app_layout.repo_path, "rev-parse", "HEAD")

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret != 0
    assert "0123456" in out
    assert _read(work) == "unsaved\n"
    assert _git(app_layout.repo_path, "rev-parse", "HEAD") == head


@pytest.fixture
def with_dep(app_layout):
    """A stamped app with one dep ``../dep1``; its checkout path."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    be = app_layout.create_repo(repo_name="dep1", repo_type="git")
    deps = {
        "../": {
            "test_repo_0": {
                "vcs_type": app_layout.be_type,
                "remote": app_layout._app_backend.be.remote(),
            },
            "dep1": {"vcs_type": "git", "remote": be.be.remote()},
        }
    }
    be.__del__()
    app_layout.write_conf(params["app_conf_path"], deps=deps)
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    return app_layout._repos["dep1"]["path"]


def test_restore_moves_a_dep_back_to_its_recorded_commit(app_layout, capfd, with_dep):
    _write(os.path.join(app_layout.repo_path, "work.txt"), "snapshot\n")
    recorded = _git(with_dep, "rev-parse", "HEAD")
    verstr = _create(app_layout, capfd)
    app_layout.write_file_commit_and_push("dep1", "later.txt", "later\n")
    assert _git(with_dep, "rev-parse", "HEAD") != recorded

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 0, out
    assert _git(with_dep, "rev-parse", "HEAD") == recorded


def test_restore_resets_a_dirty_dep_and_applies_its_patch(app_layout, capfd, with_dep):
    dep_file = os.path.join(with_dep, "a", "b", "c.txt")
    _write(dep_file, "SNAPSHOT\n")
    verstr = _create(app_layout, capfd)
    _write(dep_file, "OTHER\n")
    _write(os.path.join(with_dep, "stray.txt"), "stray\n")

    ret, out = _restore(app_layout, capfd, verstr)

    assert ret == 0, out
    assert _read(dep_file) == "SNAPSHOT\n"
    assert not os.path.exists(os.path.join(with_dep, "stray.txt"))


def _corrupt_dep_patches(app_layout):
    code_root = os.path.join(app_layout.repo_path, ".vmn", "store", "code")
    corrupted = 0
    for dirpath, _, filenames in os.walk(code_root):
        if os.sep + "deps" + os.sep not in dirpath + os.sep:
            continue
        for name in filenames:
            if "working_tree" in name:
                _write(os.path.join(dirpath, name), "garbage that is no diff\n")
                corrupted += 1
    assert corrupted


def test_restore_fails_when_a_dep_patch_does_not_apply(app_layout, capfd, with_dep):
    dep_file = os.path.join(with_dep, "a", "b", "c.txt")
    _write(dep_file, "SNAPSHOT\n")
    verstr = _create(app_layout, capfd)
    _corrupt_dep_patches(app_layout)

    ret, _ = _restore(app_layout, capfd, verstr)

    assert ret != 0

"""Tests for vmn goto when sibling deps are in detached HEAD with stale objects."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger


def _run(cmd, cwd):
    subprocess.check_call(cmd, cwd=cwd, shell=isinstance(cmd, str))


@pytest.fixture
def stale_workspace(tmp_path):
    """Build a multi-repo workspace where dep is detached and stale.

    Layout:
        <tmp>/remotes/{app,dep}.git   bare upstreams
        <tmp>/work/app                primary, vmn-stamped, depends on ../dep
        <tmp>/work/dep                sibling clone

    After setup the dep upstream has a new commit that the local dep clone
    does NOT have.  Both local repos are left in detached HEAD.
    """
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    work = tmp_path / "work"
    work.mkdir()

    for name in ("app", "dep"):
        bare = remotes / f"{name}.git"
        _run(f"git init --bare --initial-branch=master {bare}", cwd=tmp_path)
        local = work / name
        _run(f"git clone {bare} {local}", cwd=tmp_path)
        _run("git checkout -b master", cwd=local)
        (local / "init.txt").write_text(name)
        _run("git add . && git -c user.email=t@t -c user.name=t commit -m init", cwd=local)
        _run("git push -u origin master", cwd=local)

    app_dir = work / "app"

    # vmn init + init-app + configure dep + stamp
    os.environ["VMN_WORKING_DIR"] = str(app_dir)
    reset_logger()
    err, _ = vmn_run(["init"])
    assert err == 0, "vmn init failed"

    reset_logger()
    err, _ = vmn_run(["init-app", "-v", "0.0.0", "myapp"])
    assert err == 0, "vmn init-app failed"

    # Write conf with dep as a dependency
    conf_path = app_dir / ".vmn" / "myapp" / "conf.yml"
    conf_data = {
        "conf": {
            "deps": {
                "../": {
                    "dep": {
                        "vcs_type": "git",
                        "remote": str(remotes / "dep.git"),
                    }
                }
            }
        }
    }
    with open(conf_path, "w") as f:
        yaml.dump(conf_data, f)

    _run("git add . && git -c user.email=t@t -c user.name=t commit -m 'add conf'", cwd=app_dir)
    _run("git push origin master", cwd=app_dir)

    # Advance dep locally so that when we stamp, the recorded changeset
    # is a commit that we can later remove from the local clone.
    dep_dir = work / "dep"
    (dep_dir / "new.txt").write_text("advance")
    _run("git add . && git -c user.email=t@t -c user.name=t commit -m advance", cwd=dep_dir)
    _run("git push origin master", cwd=dep_dir)

    # Stamp myapp 0.0.1 — this records dep at the advanced commit
    reset_logger()
    err, _ = vmn_run(["stamp", "-r", "patch", "myapp"])
    assert err == 0, "Initial stamp failed"

    # Make local dep stale by removing and re-cloning at depth=1 from a
    # separate bare that only has the initial commit.  This ensures the
    # object DB truly lacks the SHA recorded in the stamp tag.
    import shutil
    shutil.rmtree(str(dep_dir))
    # Clone from a shallow depth that excludes the advanced commit
    # We use --single-branch --depth=1 and then reset to initial commit
    # Actually simplest: create a fresh bare with only the first commit
    stale_bare = tmp_path / "stale_dep.git"
    _run(f"git clone --bare {remotes / 'dep.git'} {stale_bare}", cwd=tmp_path)
    # Remove the advanced commit from this bare by resetting its master
    initial_sha = subprocess.check_output(
        "git rev-list --max-parents=0 HEAD",
        cwd=str(stale_bare), shell=True
    ).decode().strip()
    _run(f"git update-ref refs/heads/master {initial_sha}", cwd=stale_bare)
    _run("git gc --prune=now", cwd=stale_bare)
    # Clone from this stale bare — the new dep won't have the advanced commit
    _run(f"git clone {stale_bare} {dep_dir}", cwd=tmp_path)
    # Point origin back to the real remote so --pull can fetch the missing commit
    _run(f"git remote set-url origin {remotes / 'dep.git'}", cwd=dep_dir)

    # Detach all local working copies
    for name in ("app", "dep"):
        _run("git checkout --detach HEAD", cwd=work / name)

    yield str(app_dir)

    # Cleanup env
    os.environ.pop("VMN_WORKING_DIR", None)


@pytest.fixture
def branched_workspace(tmp_path):
    """Like stale_workspace but siblings stay on master (not detached)."""
    remotes = tmp_path / "remotes"
    remotes.mkdir()
    work = tmp_path / "work"
    work.mkdir()

    for name in ("app", "dep"):
        bare = remotes / f"{name}.git"
        _run(f"git init --bare --initial-branch=master {bare}", cwd=tmp_path)
        local = work / name
        _run(f"git clone {bare} {local}", cwd=tmp_path)
        _run("git checkout -b master", cwd=local)
        (local / "init.txt").write_text(name)
        _run("git add . && git -c user.email=t@t -c user.name=t commit -m init", cwd=local)
        _run("git push -u origin master", cwd=local)

    app_dir = work / "app"

    os.environ["VMN_WORKING_DIR"] = str(app_dir)
    reset_logger()
    err, _ = vmn_run(["init"])
    assert err == 0

    reset_logger()
    err, _ = vmn_run(["init-app", "-v", "0.0.0", "myapp"])
    assert err == 0

    conf_path = app_dir / ".vmn" / "myapp" / "conf.yml"
    conf_data = {
        "conf": {
            "deps": {
                "../": {
                    "dep": {
                        "vcs_type": "git",
                        "remote": str(remotes / "dep.git"),
                    }
                }
            }
        }
    }
    with open(conf_path, "w") as f:
        yaml.dump(conf_data, f)

    _run("git add . && git -c user.email=t@t -c user.name=t commit -m 'add conf'", cwd=app_dir)
    _run("git push origin master", cwd=app_dir)

    reset_logger()
    err, _ = vmn_run(["stamp", "-r", "patch", "myapp"])
    assert err == 0

    yield str(app_dir)

    os.environ.pop("VMN_WORKING_DIR", None)


def test_goto_without_pull_surfaces_real_git_error(stale_workspace, caplog):
    """When goto fails because dep is missing commits, the error message
    must include the real git reason (e.g. 'reference is not a tree' or
    'unable to read tree')."""
    os.environ["VMN_WORKING_DIR"] = stale_workspace
    reset_logger()
    err, _ = vmn_run(["goto", "myapp", "-v", "0.0.1"])
    assert err != 0

    log = (Path(stale_workspace) / ".vmn" / "vmn.log").read_text()
    failed_lines = [l for l in log.split("\n") if "Failed to update" in l]
    assert any(
        "reference is not a tree" in l or "unable to read tree" in l
        for l in failed_lines
    ), (
        f"Expected git error reason in 'Failed to update' line, got: {failed_lines}"
    )


def test_goto_without_pull_hints_at_pull_flag(stale_workspace):
    """When goto fails with stale objects, hint the user to re-run with --pull."""
    os.environ["VMN_WORKING_DIR"] = stale_workspace
    reset_logger()
    err, _ = vmn_run(["goto", "myapp", "-v", "0.0.1"])
    assert err != 0

    log = (Path(stale_workspace) / ".vmn" / "vmn.log").read_text()
    assert "Re-run with --pull" in log or "re-run with --pull" in log.lower()


def test_goto_with_pull_succeeds_in_detached_head(stale_workspace):
    """With --pull, goto must succeed even when siblings are in detached HEAD.
    It should fall back to fetch instead of raising 'Will not pull in detached head'."""
    os.environ["VMN_WORKING_DIR"] = stale_workspace
    reset_logger()
    err, _ = vmn_run(["goto", "myapp", "-v", "0.0.1", "--pull"])
    assert err == 0

    log = (Path(stale_workspace) / ".vmn" / "vmn.log").read_text()
    assert "fetching instead of pulling" in log.lower()


def test_pull_on_branch_still_uses_selected_remote_pull(branched_workspace, monkeypatch):
    """Regression: when NOT in detached HEAD, pull() must still call
    selected_remote.pull('--ff-only'), not the fetch fallback."""
    os.environ["VMN_WORKING_DIR"] = branched_workspace

    pull_calls = []

    from git import Remote
    original_pull_fn = Remote.pull

    def spy_pull(self, *args, **kwargs):
        pull_calls.append(("selected_remote.pull", args))
        return original_pull_fn(self, *args, **kwargs)

    monkeypatch.setattr(Remote, "pull", spy_pull)

    reset_logger()
    err, _ = vmn_run(["goto", "myapp", "-v", "0.0.1", "--pull"])

    # pull() should have been called via selected_remote.pull
    assert any("selected_remote.pull" in str(c) for c in pull_calls), (
        f"Expected selected_remote.pull to be called, got: {pull_calls}"
    )

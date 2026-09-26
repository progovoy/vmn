"""Shared setup for island integration tests (app + dependency + island)."""
import subprocess
from pathlib import Path

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.cli.entry import vmn_run


def _git(path, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=check
    )


def _out(path, *args):
    return _git(path, *args).stdout.strip()


def _commit(path, name, content=None):
    """Commit a file; sets an identity so it works in repos without git config."""
    (Path(path) / name).write_text(content or name)
    _git(path, "add", name)
    _git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", name)


def _remote_refs(remote):
    return subprocess.check_output(
        ["git", "--git-dir", remote, "for-each-ref"], text=True
    )


def _app_with_dep(app_layout, dep_branch=None):
    """Stamp an app whose conf pins ../dep_repo. Returns (dep_path, dep_branch)."""
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    app_layout.create_repo(repo_name="dep_repo", repo_type="git")
    dep_path = app_layout._repos["dep_repo"]["path"]
    branch = dep_branch or _out(dep_path, "branch", "--show-current")
    app_layout.write_conf(
        params["app_conf_path"],
        deps={"../": {"dep_repo": {"vcs_type": "git", "branch": branch}}},
    )
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    return dep_path, branch


def _create_island(app_layout, tmp_path, name, *extra):
    base = tmp_path / "islands"
    rc = vmn_run(
        [
            "wt",
            "create",
            app_layout.app_name,
            "--island-name",
            name,
            "--base-path",
            str(base),
            *extra,
        ]
    )[0]
    return rc, base / name


def _island_a(app_layout, island):
    return island / Path(app_layout.repo_path).name

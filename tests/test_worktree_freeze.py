import subprocess
from types import SimpleNamespace

import pytest
import yaml

from version_stamp.cli.worktree_freeze import worktree_freeze
from version_stamp.core.logging import init_stamp_logger
from island_helpers import _commit, _git


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def _clone_with_remote(tmp_path, name):
    remote = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True)
    _git(repo, "checkout", "-q", "-b", "main")
    _commit(repo, "init")
    _git(repo, "push", "-q", "-u", "origin", "main")
    return repo


def _write_conf(path, deps, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"conf": {"deps": deps, **extra}}))


def _read_conf(path):
    return yaml.safe_load(path.read_text())["conf"]


@pytest.fixture
def layout(tmp_path):
    main = _clone_with_remote(tmp_path, "main")
    dep = _clone_with_remote(tmp_path, "dep")
    app_dir = main / ".vmn" / "app"
    _write_conf(
        app_dir / "conf.yml",
        {"../": {"dep": {"vcs_type": "git", "branch": "main"}}},
        template="[{major}]",
    )
    _git(main, "checkout", "-q", "-b", "feature/x")
    ctx = SimpleNamespace(
        vcs=SimpleNamespace(vmn_root_path=str(main), app_dir_path=str(app_dir)),
        args=SimpleNamespace(),
    )
    branch_conf = app_dir / "branch_conf" / "feature" / "x" / "conf.yml"
    return SimpleNamespace(main=main, dep=dep, app_dir=app_dir, ctx=ctx, conf=branch_conf)


def test_refuses_on_island_branch(layout, caplog):
    _git(layout.main, "checkout", "-q", "-b", "island/i/main")

    assert worktree_freeze(layout.ctx) == 1

    assert "git checkout -b" in caplog.text
    assert not (layout.app_dir / "branch_conf").exists()


def test_refuses_on_detached_head(layout):
    _git(layout.main, "checkout", "-q", "--detach")

    assert worktree_freeze(layout.ctx) == 1
    assert not (layout.app_dir / "branch_conf").exists()


def test_pins_dep_to_its_real_branch_in_the_current_branch_conf(layout):
    _git(layout.dep, "checkout", "-q", "-b", "feature/b")
    _commit(layout.dep, "b")
    _git(layout.dep, "push", "-q", "-u", "origin", "feature/b")

    assert worktree_freeze(layout.ctx) == 0

    conf = _read_conf(layout.conf)
    assert conf["deps"]["../"]["dep"]["branch"] == "feature/b"
    assert conf["template"] == "[{major}]"


def test_replaces_hash_pin_with_branch(layout):
    _write_conf(
        layout.app_dir / "conf.yml", {"../": {"dep": {"vcs_type": "git", "hash": "abc"}}}
    )
    _git(layout.dep, "checkout", "-q", "-b", "feature/b")
    _git(layout.dep, "push", "-q", "-u", "origin", "feature/b")

    assert worktree_freeze(layout.ctx) == 0

    dep_conf = _read_conf(layout.conf)["deps"]["../"]["dep"]
    assert dep_conf["branch"] == "feature/b"
    assert "hash" not in dep_conf


def _dep_on_island_branch(layout):
    _git(layout.dep, "checkout", "-q", "-b", "island/i/main")
    _git(layout.dep, "branch", "-q", "--set-upstream-to=origin/main")


def test_refuses_when_dep_has_commits_only_on_its_private_branch(layout, caplog):
    _dep_on_island_branch(layout)
    _commit(layout.dep, "private")

    assert worktree_freeze(layout.ctx) == 1

    assert "island/i/main" in caplog.text
    assert not layout.conf.exists()


def test_untouched_private_dep_keeps_its_pin_and_writes_nothing(layout, caplog):
    _dep_on_island_branch(layout)

    assert worktree_freeze(layout.ctx) == 0

    assert "Nothing to freeze" in caplog.text
    assert not layout.conf.exists()


def test_updates_existing_branch_conf_in_place(layout):
    _write_conf(
        layout.conf,
        {"../": {"dep": {"vcs_type": "git", "branch": "main"}}},
        template="[{major}].[{minor}]",
    )
    _git(layout.dep, "checkout", "-q", "-b", "feature/b")
    _git(layout.dep, "push", "-q", "-u", "origin", "feature/b")

    assert worktree_freeze(layout.ctx) == 0

    conf = _read_conf(layout.conf)
    assert conf["template"] == "[{major}].[{minor}]"
    assert conf["deps"]["../"]["dep"]["branch"] == "feature/b"


def test_warns_when_dep_branch_was_never_pushed(layout, caplog):
    _git(layout.dep, "checkout", "-q", "-b", "feature/b")

    assert worktree_freeze(layout.ctx) == 0

    assert "git push -u origin feature/b" in caplog.text
    assert _read_conf(layout.conf)["deps"]["../"]["dep"]["branch"] == "feature/b"

import json
import os
import subprocess
from types import SimpleNamespace

from version_stamp.cli import worktrees
from version_stamp.core.logging import init_stamp_logger


init_stamp_logger()


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _new_repo(path):
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "VMN Tests")
    _git(path, "config", "user.email", "vmn@example.com")
    (path / "value.txt").write_text("one")
    _git(path, "add", "value.txt")
    _git(path, "commit", "-m", "first")
    first = _git(path, "rev-parse", "HEAD")
    (path / "value.txt").write_text("two")
    _git(path, "commit", "-am", "second")
    return first, _git(path, "rev-parse", "HEAD")


def _version_ctx(repo, version, changesets=None):
    tag = f"app_{version}"
    app = {"_version": version}
    if changesets is not None:
        app["changesets"] = changesets
    ver_infos = {tag: {"ver_info": {"stamping": {"app": app}}}}
    backend = SimpleNamespace(changeset=lambda requested: _git(repo, "rev-parse", requested))
    vcs = SimpleNamespace(
        backend=backend,
        configured_deps={"../current": {"remote": "current"}},
        get_version_info_from_verstr=lambda requested: (tag, ver_infos),
    )
    return SimpleNamespace(vcs=vcs)


def test_version_source_starts_main_worktree_at_tagged_commit(tmp_path):
    repo = tmp_path / "main"
    first, second = _new_repo(repo)
    _git(repo, "tag", "app_1.0.0", first)
    ctx = _version_ctx(repo, "1.0.0", {".": {"hash": first}})
    source = {"type": "version", "ref": "1.0.0"}

    assert worktrees._resolve_version_source(ctx, source)
    dest = tmp_path / "island"
    assert worktrees._create_main_worktree(repo, dest, "island/test/main", source) == 0

    assert _git(dest, "rev-parse", "HEAD") == first
    assert _git(dest, "rev-parse", "HEAD") != second


def test_invalid_version_is_rejected_before_island_directory_is_created(tmp_path):
    repo = tmp_path / "main"
    _new_repo(repo)
    vcs = SimpleNamespace(
        vmn_root_path=str(repo),
        name="app",
        get_version_info_from_verstr=lambda version: ("app_missing", {}),
    )
    args = SimpleNamespace(
        base_path=str(tmp_path / "islands"),
        editable_dep=None,
        from_branch=None,
        from_version="missing",
        island_name="bad-version",
        no_stamp=False,
        shallow_deps=False,
    )

    assert worktrees.worktree_create(SimpleNamespace(args=args, vcs=vcs)) == 1
    assert not (tmp_path / "islands" / "bad-version").exists()


def test_version_with_zero_dependencies_does_not_fall_back_to_current_config():
    ctx = _version_ctx("/unused", "1.0.0", {".": {"hash": "abc"}})
    source = {"type": "version", "ref": "1.0.0"}

    assert worktrees._resolve_deps(ctx, source) == {}


def test_dependency_basename_collision_is_rejected():
    vcs = SimpleNamespace(
        actual_deps_state={},
        configured_deps={
            "../one/shared": {"remote": "one"},
            "../two/shared": {"remote": "two"},
        },
    )

    assert worktrees._deps_from_configured(SimpleNamespace(vcs=vcs)) is None


def test_unknown_editable_dependency_is_rejected(tmp_path, caplog):
    main = tmp_path / "main"
    dep = tmp_path / "known"
    _new_repo(main)
    _new_repo(dep)
    vcs = SimpleNamespace(
        actual_deps_state={},
        configured_deps={"../known": {"remote": None}},
        name="app",
        selected_tag=None,
        ver_infos_from_repo={},
        vmn_root_path=str(main),
    )
    args = SimpleNamespace(
        base_path=str(tmp_path / "islands"),
        editable_dep=["typo"],
        from_branch=None,
        from_version=None,
        island_name="bad-editable",
        no_stamp=False,
        shallow_deps=False,
    )

    assert worktrees.worktree_create(SimpleNamespace(args=args, vcs=vcs)) == 1
    assert "Unknown --editable-dep: typo" in caplog.text
    assert not (tmp_path / "islands" / "bad-editable").exists()


def test_shallow_editable_dep_finishes_at_recorded_hash(tmp_path):
    source = tmp_path / "dep"
    first, second = _new_repo(source)
    remote = tmp_path / "dep.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(remote)],
        check=True,
        capture_output=True,
    )
    dest = tmp_path / "dep-island"
    info = {"remote": f"file://{remote}", "branch": "main", "hash": first}

    assert worktrees._shallow_clone_dep(info, dest, "island/demo/dep") == 0
    assert _git(dest, "rev-parse", "HEAD") == first
    assert _git(dest, "branch", "--show-current") == "island/demo/dep"
    assert _git(dest, "rev-parse", "HEAD") != second


def test_no_stamp_marker_is_written_to_main_and_dependency_checkouts(tmp_path):
    main = tmp_path / "main"
    dep = tmp_path / "dep"
    main.mkdir()
    dep.mkdir()

    worktrees._write_island_markers([main, dep], readonly=True)

    for checkout in (main, dep):
        assert (checkout / ".vmn" / worktrees.WORKTREE_ISLAND_MARKER).is_file()
        assert (checkout / ".vmn" / worktrees.WORKTREE_READONLY_MARKER).is_file()

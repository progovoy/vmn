import json
import os
import subprocess
from types import SimpleNamespace

from version_stamp.cli import worktree_create, worktree_sources
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
    backend = SimpleNamespace(
        changeset=lambda requested: _git(repo, "rev-parse", requested)
    )
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

    assert worktree_create._resolve_version_source(ctx, source)
    dest = tmp_path / "island"
    assert worktree_create._create_main_worktree(repo, dest, "island/test/main", source) == 0

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
        from_branch=None,
        from_version="missing",
        island_name="bad-version",
        shallow_deps=False,
    )

    assert worktree_create.worktree_create(SimpleNamespace(args=args, vcs=vcs)) == 1
    assert not (tmp_path / "islands" / "bad-version").exists()


def test_version_with_zero_dependencies_does_not_fall_back_to_current_config():
    ctx = _version_ctx("/unused", "1.0.0", {".": {"hash": "abc"}})
    source = {"type": "version", "ref": "1.0.0"}

    assert worktree_create._resolve_deps(ctx, source) == {}


def test_dependency_basename_collision_is_rejected():
    vcs = SimpleNamespace(
        actual_deps_state={},
        configured_deps={
            "../one/shared": {"remote": "one"},
            "../two/shared": {"remote": "two"},
        },
    )

    assert worktree_sources.deps_from_configured(SimpleNamespace(vcs=vcs)) is None


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

    assert worktree_create._shallow_clone_dep(info, dest, "island/demo/dep") == 0
    assert _git(dest, "rev-parse", "HEAD") == first
    assert _git(dest, "branch", "--show-current") == "island/demo/dep"
    assert _git(dest, "rev-parse", "HEAD") != second


def _pinned_ctx(main, configured, actual=None):
    vcs = SimpleNamespace(
        actual_deps_state=actual or {},
        configured_deps=configured,
        vmn_root_path=str(main),
    )
    return SimpleNamespace(vcs=vcs)


def _dep_ctx(tmp_path, conf, local=None):
    main = tmp_path / "main"
    main.mkdir(exist_ok=True)
    dep = tmp_path / "dep"
    first, second = _new_repo(dep)
    if local == "other":
        _git(dep, "checkout", "-b", "elsewhere")
    elif local == "detached":
        _git(dep, "checkout", "--detach", "HEAD")
    elif local == "missing":
        import shutil

        shutil.rmtree(dep)
    actual = {"../dep": {"hash": second, "remote": "file:///r"}}
    return _pinned_ctx(main, {"../dep": conf}, actual), first, second


def test_dep_pinned_by_hash_starts_at_that_hash(tmp_path):
    ctx, first, _ = _dep_ctx(tmp_path, {"hash": "abc123"})

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        "abc123",
        None,
        False,
    )


def test_dep_pinned_by_tag_starts_at_that_tag(tmp_path):
    ctx, _, _ = _dep_ctx(tmp_path, {"tag": "v1"})

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        "v1",
        None,
        False,
    )


def test_dep_pinned_branch_with_local_on_that_branch_uses_local_hash(tmp_path):
    ctx, _, second = _dep_ctx(tmp_path, {"branch": "main"})

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        second,
        "main",
        False,
    )


def test_dep_pinned_branch_with_local_elsewhere_fetches_the_pinned_branch(tmp_path):
    ctx, _, _ = _dep_ctx(tmp_path, {"branch": "main"}, local="other")

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        "vmn-readonly/main",
        "main",
        True,
    )


def test_dep_pinned_branch_with_missing_local_fetches_the_pinned_branch(tmp_path):
    ctx, _, _ = _dep_ctx(tmp_path, {"branch": "release/1"}, local="missing")

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        "vmn-readonly/release/1",
        "release/1",
        True,
    )


def test_unpinned_dep_on_a_branch_uses_that_branch_at_local_hash(tmp_path):
    ctx, _, second = _dep_ctx(tmp_path, {}, local="other")

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        second,
        "elsewhere",
        False,
    )


def test_unpinned_detached_dep_has_no_source_branch(tmp_path):
    ctx, _, second = _dep_ctx(tmp_path, {}, local="detached")

    dep = worktree_sources.deps_from_configured(ctx)["dep"]

    assert (dep["start_point"], dep["source_branch"], dep["fetch"]) == (
        second,
        None,
        False,
    )


def test_deps_from_version_have_no_source_branch():
    deps = worktree_sources.deps_from_version(
        _version_ctx("/unused", "1.0.0", {"../dep": {"hash": "abc"}}), "1.0.0"
    )

    assert deps["dep"]["start_point"] == "abc"
    assert deps["dep"]["source_branch"] is None
    assert deps["dep"]["fetch"] is False

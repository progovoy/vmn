import json
import subprocess
from types import SimpleNamespace

from version_stamp.cli import worktrees
from version_stamp.cli.args import parse_user_commands
from version_stamp.core.logging import init_stamp_logger


init_stamp_logger()


def _git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(path):
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "VMN Tests")
    _git(path, "config", "user.email", "vmn@example.com")
    (path / "file").write_text("data")
    _git(path, "add", "file")
    _git(path, "commit", "-m", "initial")


def _registered(repo, path):
    output = _git(repo, "worktree", "list", "--porcelain")
    return f"worktree {path}" in output.splitlines()


def _remove_ctx(main_repo, base_path, name):
    args = SimpleNamespace(base_path=str(base_path), name=name)
    vcs = SimpleNamespace(vmn_root_path=str(main_repo))
    return SimpleNamespace(args=args, vcs=vcs)


def test_list_skips_corrupt_manifests(tmp_path, capsys):
    main_repo = tmp_path / "main"
    base = tmp_path / "islands"
    valid = base / "valid"
    corrupt = base / "corrupt"
    valid.mkdir(parents=True)
    corrupt.mkdir()
    (valid / worktrees.ISLAND_MANIFEST_FILENAME).write_text(json.dumps({
        "name": "valid",
        "app_name": "app",
        "version": "1.2.3",
        "source": {"type": "branch", "ref": "main"},
        "created_at": "now",
    }))
    (corrupt / worktrees.ISLAND_MANIFEST_FILENAME).write_text("not json")
    ctx = SimpleNamespace(
        args=SimpleNamespace(base_path=str(base)),
        vcs=SimpleNamespace(vmn_root_path=str(main_repo)),
    )

    assert worktrees.worktree_list(ctx) == 0
    assert "valid" in capsys.readouterr().out


def test_worktrees_shorthand_and_action_requirements():
    shorthand = parse_user_commands(["worktrees", "my_app"])
    assert shorthand.action == "create"
    assert shorthand.name == "my_app"

    explicit = parse_user_commands(["worktrees", "create", "my_app"])
    assert explicit.action == "create"
    assert explicit.name == "my_app"

    for command in (["worktrees"], ["worktrees", "create"], ["worktrees", "remove"]):
        try:
            parse_user_commands(command)
        except (RuntimeError, SystemExit):
            pass
        else:
            raise AssertionError(f"command should require a name: {command}")

    listed = parse_user_commands(["worktrees", "list"])
    assert listed.action == "list"
    assert listed.name is None


def test_remove_cleans_detached_and_editable_dep_registrations(tmp_path):
    main_repo = tmp_path / "main"
    detached_repo = tmp_path / "detached"
    editable_repo = tmp_path / "editable"
    for repo in (main_repo, detached_repo, editable_repo):
        _repo(repo)

    base = tmp_path / "islands"
    island = base / "demo"
    island.mkdir(parents=True)
    main_wt = island / "main"
    detached_wt = island / "detached"
    editable_wt = island / "editable"
    _git(main_repo, "worktree", "add", "-b", "island/demo/main", str(main_wt))
    _git(detached_repo, "worktree", "add", "--detach", str(detached_wt))
    _git(editable_repo, "worktree", "add", "-b", "island/demo/editable", str(editable_wt))
    manifest = {
        "main_repo": {
            "path": str(main_wt),
            "branch": "island/demo/main",
            "source_path": str(main_repo),
        },
        "deps": {
            "detached": {
                "path": str(detached_wt),
                "branch": None,
                "source_path": str(detached_repo),
            },
            "editable": {
                "path": str(editable_wt),
                "branch": "island/demo/editable",
                "source_path": str(editable_repo),
            },
        },
    }
    (island / worktrees.ISLAND_MANIFEST_FILENAME).write_text(json.dumps(manifest))

    assert worktrees.worktree_remove(_remove_ctx(main_repo, base, "demo")) == 0
    assert not _registered(main_repo, main_wt)
    assert not _registered(detached_repo, detached_wt)
    assert not _registered(editable_repo, editable_wt)
    assert not island.exists()


def test_remove_failure_keeps_manifest_for_retry(tmp_path, monkeypatch):
    main_repo = tmp_path / "main"
    dep_repo = tmp_path / "dep"
    _repo(main_repo)
    _repo(dep_repo)
    base = tmp_path / "islands"
    island = base / "demo"
    island.mkdir(parents=True)
    dep_wt = island / "dep"
    _git(dep_repo, "worktree", "add", "--detach", str(dep_wt))
    manifest_path = island / worktrees.ISLAND_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps({
        "main_repo": {"path": str(island / "main"), "branch": None, "source_path": str(main_repo)},
        "deps": {"dep": {"path": str(dep_wt), "branch": None, "source_path": str(dep_repo)}},
    }))
    real_run_git = worktrees._run_git

    def fail_dep_remove(repo, args):
        if str(repo) == str(dep_repo) and args[:2] == ["worktree", "remove"]:
            return subprocess.CompletedProcess([], 1, "", "injected failure")
        return real_run_git(repo, args)

    monkeypatch.setattr(worktrees, "_run_git", fail_dep_remove)

    assert worktrees.worktree_remove(_remove_ctx(main_repo, base, "demo")) == 1
    assert manifest_path.is_file()
    assert _registered(dep_repo, dep_wt)


def test_remove_repairs_legacy_manifest_without_dep_source_path(tmp_path):
    main_repo = tmp_path / "main"
    dep_repo = tmp_path / "dep"
    _repo(main_repo)
    _repo(dep_repo)
    base = tmp_path / "islands"
    island = base / "legacy"
    island.mkdir(parents=True)
    dep_wt = island / "dep"
    _git(dep_repo, "worktree", "add", "--detach", str(dep_wt))
    (island / worktrees.ISLAND_MANIFEST_FILENAME).write_text(json.dumps({
        "main_repo": {"path": str(island / "main"), "branch": None},
        "deps": {"dep": {"path": str(dep_wt), "branch": None}},
    }))

    assert worktrees.worktree_remove(_remove_ctx(main_repo, base, "legacy")) == 0
    assert not _registered(dep_repo, dep_wt)
    assert not island.exists()


def test_rollback_uses_each_dependency_source_repo(tmp_path):
    calls = []

    def record(repo, args):
        calls.append((str(repo), args))
        if str(repo) == "/source/dep" and args == ["worktree", "list", "--porcelain"]:
            return subprocess.CompletedProcess([], 0, "worktree /island/dep\n", "")
        return subprocess.CompletedProcess([], 0, "", "")

    dep_manifests = {
        "detached": {"path": "/island/dep", "branch": None, "source_path": "/source/dep"},
    }

    assert worktrees._cleanup_island(
        "/source/main", "/island/main", "island/demo/main", dep_manifests, run_git=record
    )
    assert ("/source/dep", ["worktree", "remove", "--force", "/island/dep"]) in calls

from pathlib import Path
import subprocess
from types import SimpleNamespace

from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.backends.git_ops import GitOpsMixin
from version_stamp.cli import commands, entry, worktrees
from version_stamp.cli.entry import vmn_run
from version_stamp.stamping.publisher import _push_published_refs


class Args(SimpleNamespace):
    def __contains__(self, name):
        return hasattr(self, name)


def test_local_only_island_skips_remote_branch_preparation(tmp_path, monkeypatch):
    vmn_dir = tmp_path / ".vmn"
    vmn_dir.mkdir()
    (vmn_dir / worktrees.WORKTREE_ISLAND_MARKER).touch()
    prepare_calls = []
    backend = SimpleNamespace(
        selected_remote=object(),
        prepare_for_remote_operation=lambda: prepare_calls.append(True) or 1,
    )
    vcs = SimpleNamespace(backend=backend, name=None)
    ctx = SimpleNamespace(args=Args(command="stamp", pull=False), vcs=vcs)
    monkeypatch.setattr(entry, "VMNContainer", lambda args, root: ctx)
    monkeypatch.setattr(entry, "handle_stamp", lambda vmn_ctx: 0)

    assert entry._vmn_run(ctx.args, str(tmp_path)) == (0, ctx)
    assert prepare_calls == []


def test_local_only_publish_pushes_tags_without_branch():
    calls = []
    backend = SimpleNamespace(
        push=lambda tags: calls.append(("branch", tags)),
        push_tags=lambda tags: calls.append(("tags", tags)),
        check_for_outgoing_changes=lambda: "local island commits are outgoing",
    )

    _push_published_refs(backend, ["app_1.2.3"], local_only=True)

    assert calls == [("tags", ["app_1.2.3"])]


def test_normal_publish_still_pushes_branch_and_checks_outgoing():
    calls = []
    backend = SimpleNamespace(
        push=lambda tags: calls.append(("branch", tags)),
        push_tags=lambda tags: calls.append(("tags", tags)),
        check_for_outgoing_changes=lambda: None,
    )

    _push_published_refs(backend, ["app_1.2.3"], local_only=False)

    assert calls == [("branch", ["app_1.2.3"])]


def test_git_backend_can_push_tags_without_remote_branch():
    calls = []
    backend = object.__new__(GitOpsMixin)
    backend.selected_remote = object()
    backend._push_with_ci_skip_fallback = calls.append

    backend.push_tags(["app_1.2.3", "root_4"])

    assert calls == ["refs/tags/app_1.2.3", "refs/tags/root_4"]


def test_no_stamp_marker_takes_precedence_over_local_only_marker(tmp_path):
    worktrees._write_island_markers([tmp_path], readonly=True)

    assert worktrees.is_local_only_island(tmp_path)
    assert (Path(tmp_path) / ".vmn" / worktrees.WORKTREE_READONLY_MARKER).is_file()


def test_local_only_stamp_pull_fetches_without_merging_branch():
    calls = []
    vcs = SimpleNamespace(
        backend=SimpleNamespace(
            perform_cached_fetch=lambda force=False: calls.append(("fetch", force))
        ),
        retrieve_remote_changes=lambda: calls.append(("pull", None)),
    )

    commands._retrieve_stamp_updates(vcs, local_only=True)

    assert calls == [("fetch", True)]


def test_editable_island_dep_may_diverge_from_config_during_stamp(tmp_path):
    worktrees._write_island_markers([tmp_path], readonly=False)
    editable_backend = SimpleNamespace(in_detached_head=lambda: False)

    assert commands._is_editable_island_dep(
        str(tmp_path), editable_backend, {"outgoing"}
    )
    assert not commands._is_editable_island_dep(
        str(tmp_path), editable_backend, set()
    )


def test_stamp_in_local_island_pushes_tag_but_not_island_branch(
    app_layout, tmp_path
):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    remote = app_layout.test_app_remote
    branch = subprocess.check_output(
        ["git", "-C", app_layout.repo_path, "branch", "--show-current"], text=True
    ).strip()
    remote_branch_before = subprocess.check_output(
        ["git", "--git-dir", remote, "rev-parse", branch], text=True
    ).strip()
    base_path = tmp_path / "islands"

    assert vmn_run([
        "worktrees", "create", app_layout.app_name,
        "--island-name", "stamp-test", "--base-path", str(base_path),
    ])[0] == 0
    island_repo = base_path / "stamp-test" / Path(app_layout.repo_path).name
    app_layout.set_working_dir(str(island_repo))
    (island_repo / "feature.txt").write_text("local feature")
    subprocess.run(["git", "add", "feature.txt"], cwd=island_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "local feature"], cwd=island_repo, check=True
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    version = ver_info["stamping"]["app"]["_version"]
    assert subprocess.check_output(
        ["git", "--git-dir", remote, "rev-parse", branch], text=True
    ).strip() == remote_branch_before
    subprocess.run(
        ["git", "--git-dir", remote, "rev-parse", f"{app_layout.app_name}_{version}^{{}}"],
        check=True,
        capture_output=True,
    )

    app_layout.set_working_dir(app_layout.repo_path)
    assert vmn_run([
        "worktrees", "remove", "stamp-test", "--base-path", str(base_path),
    ])[0] == 0

"""`vmn wt create`: source branches, dep start points, read-only upstreams."""
import json
import os
import subprocess
from pathlib import Path

from helpers import _gen, _init_app, _run_vmn_init, _stamp_app
from version_stamp.backends.git import GitBackend
from version_stamp.cli.entry import vmn_run
from version_stamp.core.constants import VMN_READONLY_REMOTE


def _git(path, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=check
    )


def _out(path, *args):
    return _git(path, *args).stdout.strip()


def _commit(path, name, content=None):
    (Path(path) / name).write_text(content or name)
    _git(path, "add", name)
    _git(path, "commit", "-q", "-m", name)


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


def test_create_tracks_source_branch_in_main_and_dep(app_layout, tmp_path):
    dep_path, dep_branch = _app_with_dep(app_layout)
    a_branch = _out(app_layout.repo_path, "branch", "--show-current")

    rc, island = _create_island(app_layout, tmp_path, "feat")

    assert rc == 0
    a, dep = _island_a(app_layout, island), island / "dep_repo"
    for repo, source, source_path in (
        (a, a_branch, app_layout.repo_path),
        (dep, dep_branch, dep_path),
    ):
        assert _out(repo, "branch", "--show-current") == f"island/feat/{source}"
        assert _out(repo, "rev-parse", "--abbrev-ref", "@{u}") == (
            f"{VMN_READONLY_REMOTE}/{source}"
        )
        assert _out(repo, "rev-parse", "HEAD") == _out(source_path, "rev-parse", "HEAD")
        fetch = _out(source_path, "config", "--get-all", f"remote.{VMN_READONLY_REMOTE}.fetch")
        assert fetch.splitlines() == [
            f"+refs/heads/{source}:refs/remotes/{VMN_READONLY_REMOTE}/{source}"
        ]
    manifest = json.loads((island / "island.json").read_text())
    assert manifest["main_repo"]["source_branch"] == a_branch
    assert manifest["main_repo"]["upstream"] == f"{VMN_READONLY_REMOTE}/{a_branch}"
    assert manifest["deps"]["dep_repo"]["source_branch"] == dep_branch
    assert manifest["deps"]["dep_repo"]["upstream"] == f"{VMN_READONLY_REMOTE}/{dep_branch}"


def test_gen_verify_version_works_in_fresh_island(app_layout, tmp_path):
    _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    template = tmp_path / "t.j2"
    template.write_text("{{version}}")
    output = tmp_path / "out.txt"
    app_layout.set_working_dir(str(_island_a(app_layout, island)))

    assert _gen(app_layout.app_name, str(template), str(output), verify_version=True) == 0

    assert output.read_text().strip()


def _push_dep_branch(dep_path, branch):
    default = _out(dep_path, "branch", "--show-current")
    _git(dep_path, "checkout", "-q", "-b", branch)
    _commit(dep_path, "feature-b.txt")
    _git(dep_path, "push", "-q", "-u", "origin", branch)
    tip = _out(dep_path, "rev-parse", "HEAD")
    _git(dep_path, "checkout", "-q", default)
    return tip


def test_dep_on_other_branch_starts_at_fetched_conf_branch(app_layout, tmp_path):
    dep_path, default = _app_with_dep(app_layout)
    tip = _push_dep_branch(dep_path, "feature/b")
    a_repo = Path(app_layout.repo_path)
    _git(a_repo, "checkout", "-q", "-b", "feature/x")
    _git(a_repo, "push", "-q", "-u", "origin", "feature/x")
    conf_dir = a_repo / ".vmn" / app_layout.app_name / "branch_conf" / "feature" / "x"
    conf_dir.mkdir(parents=True)
    app_layout.write_conf(
        str(conf_dir / "conf.yml"),
        deps={"../": {"dep_repo": {"vcs_type": "git", "branch": "feature/b"}}},
    )

    rc, island = _create_island(app_layout, tmp_path, "review")

    assert rc == 0
    dep = island / "dep_repo"
    assert _out(dep, "rev-parse", "HEAD") == tip
    assert _out(dep, "branch", "--show-current") == "island/review/feature/b"
    assert _out(dep, "rev-parse", "--abbrev-ref", "@{u}") == (
        f"{VMN_READONLY_REMOTE}/feature/b"
    )
    manifest = json.loads((island / "island.json").read_text())
    assert manifest["deps"]["dep_repo"]["source_branch"] == "feature/b"


def test_missing_conf_branch_fails_and_cleans_up(app_layout, tmp_path):
    dep_path, _ = _app_with_dep(app_layout)
    a_repo = Path(app_layout.repo_path)
    _git(a_repo, "checkout", "-q", "-b", "feature/y")
    _git(a_repo, "push", "-q", "-u", "origin", "feature/y")
    conf_dir = a_repo / ".vmn" / app_layout.app_name / "branch_conf" / "feature" / "y"
    conf_dir.mkdir(parents=True)
    app_layout.write_conf(
        str(conf_dir / "conf.yml"),
        deps={"../": {"dep_repo": {"vcs_type": "git", "branch": "no/such-branch"}}},
    )

    rc, island = _create_island(app_layout, tmp_path, "broken")

    assert rc == 1
    assert not island.exists()
    for repo in (a_repo, dep_path):
        assert _out(repo, "for-each-ref", "refs/heads/island/") == ""


def test_private_branch_refuses_git_push(app_layout, tmp_path):
    _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a = _island_a(app_layout, island)
    _commit(a, "island-work.txt")
    before = _remote_refs(app_layout.test_app_remote)

    assert _git(a, "push", check=False).returncode != 0
    assert _git(a, "-c", "push.default=upstream", "push", check=False).returncode != 0

    assert _remote_refs(app_layout.test_app_remote) == before


def test_vmn_selects_origin_inside_island(app_layout, tmp_path):
    _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0

    backend = GitBackend(str(_island_a(app_layout, island)))

    assert backend.selected_remote.name == "origin"


def test_stamp_on_real_branch_in_island_does_not_touch_source_branch(
    app_layout, tmp_path
):
    _app_with_dep(app_layout)
    a_branch = _out(app_layout.repo_path, "branch", "--show-current")
    remote = app_layout.test_app_remote
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a = _island_a(app_layout, island)
    _git(a, "checkout", "-q", "-b", "feature/y")
    _commit(a, "y.txt")
    _git(a, "push", "-q", "-u", "origin", "feature/y")
    source_before = subprocess.check_output(
        ["git", "--git-dir", remote, "rev-parse", a_branch], text=True
    )
    app_layout.set_working_dir(str(a))

    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    assert (
        subprocess.check_output(
            ["git", "--git-dir", remote, "rev-parse", a_branch], text=True
        )
        == source_before
    )


def test_create_warns_about_uncommitted_changes(app_layout, tmp_path, capfd):
    _app_with_dep(app_layout)
    (Path(app_layout.repo_path) / "wip.txt").write_text("wip")
    capfd.readouterr()

    rc, island = _create_island(app_layout, tmp_path, "feat")

    assert rc == 0
    assert "Uncommitted changes are not carried into the island" in capfd.readouterr().err
    assert not (_island_a(app_layout, island) / "wip.txt").exists()


def test_remove_drops_readonly_remote_after_last_island(app_layout, tmp_path):
    dep_path, _ = _app_with_dep(app_layout)
    base = tmp_path / "islands"
    assert _create_island(app_layout, tmp_path, "one")[0] == 0
    assert _create_island(app_layout, tmp_path, "two")[0] == 0

    def remotes():
        return _out(app_layout.repo_path, "remote").split()

    assert vmn_run(["wt", "remove", "one", "--base-path", str(base)])[0] == 0
    assert VMN_READONLY_REMOTE in remotes()
    assert vmn_run(["wt", "remove", "two", "--base-path", str(base)])[0] == 0
    assert VMN_READONLY_REMOTE not in remotes()
    assert VMN_READONLY_REMOTE not in _out(dep_path, "remote").split()


def test_stamp_refused_when_dep_has_private_commits(app_layout, tmp_path, capfd):
    _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a = _island_a(app_layout, island)
    _commit(island / "dep_repo", "private-dep-work.txt")
    _git(a, "checkout", "-q", "-b", "feature/y")
    _commit(a, "y.txt")
    _git(a, "push", "-q", "-u", "origin", "feature/y")
    app_layout.set_working_dir(str(a))
    capfd.readouterr()

    assert _stamp_app(app_layout.app_name, "patch")[0] == 1


def test_island_mirrors_nested_dep_layout_so_gen_works(app_layout, tmp_path):
    """A dep configured at ../libs/dep_repo must sit at the same relative path
    inside the island, or vmn cannot find it (the 0.10.1 island gen failure)."""
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    app_layout.create_repo(repo_name="libs/dep_repo", repo_type="git")
    dep_path = app_layout._repos["libs/dep_repo"]["path"]
    dep_branch = _out(dep_path, "branch", "--show-current")
    app_layout.write_conf(
        params["app_conf_path"],
        deps={"../libs/": {"dep_repo": {"vcs_type": "git", "branch": dep_branch}}},
    )
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0

    rc, island = _create_island(app_layout, tmp_path, "nested")

    assert rc == 0
    assert (island / "libs" / "dep_repo" / ".git").exists()
    template = tmp_path / "t.j2"
    template.write_text("{{version}}")
    app_layout.set_working_dir(str(_island_a(app_layout, island)))
    assert _gen(app_layout.app_name, str(template), str(tmp_path / "o.txt")) == 0

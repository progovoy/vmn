"""`vmn wt pull`: rebase private island branches onto their source branches."""
from pathlib import Path

from island_helpers import _app_with_dep, _commit, _create_island, _git, _island_a, _out
from version_stamp.cli.entry import vmn_run


def _advance_source(path, name):
    _commit(path, name)
    _git(path, "push", "-q")
    return _out(path, "rev-parse", "HEAD")


def _pull(*args):
    return vmn_run(["wt", "pull", *args])[0]


def _island_with_local_work(app_layout, tmp_path):
    dep_path, _ = _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a, dep = _island_a(app_layout, island), island / "dep_repo"
    _commit(a, "a-local.txt")
    _commit(dep, "dep-local.txt")
    return dep_path, island, a, dep


def _is_ancestor(repo, commit):
    return _git(repo, "merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode == 0


def test_pull_rebases_main_and_dep_onto_their_sources(app_layout, tmp_path):
    dep_path, island, a, dep = _island_with_local_work(app_layout, tmp_path)
    a_tip = _advance_source(app_layout.repo_path, "a-upstream.txt")
    dep_tip = _advance_source(dep_path, "dep-upstream.txt")
    app_layout.set_working_dir(str(a))

    assert _pull() == 0

    for repo, tip, local in ((a, a_tip, "a-local.txt"), (dep, dep_tip, "dep-local.txt")):
        assert _is_ancestor(repo, tip)
        assert _out(repo, "log", "-1", "--format=%s") == local


def test_pull_by_island_name_from_the_source_repo(app_layout, tmp_path):
    _, island, a, _ = _island_with_local_work(app_layout, tmp_path)
    a_tip = _advance_source(app_layout.repo_path, "a-upstream.txt")

    assert _pull("feat", "--base-path", str(tmp_path / "islands")) == 0

    assert _is_ancestor(a, a_tip)


def test_pull_skips_repos_moved_to_a_real_branch(app_layout, tmp_path):
    _, island, a, _ = _island_with_local_work(app_layout, tmp_path)
    _git(a, "checkout", "-q", "-b", "feature/x")
    before = _out(a, "rev-parse", "HEAD")
    _advance_source(app_layout.repo_path, "a-upstream.txt")
    app_layout.set_working_dir(str(a))

    assert _pull() == 0

    assert _out(a, "rev-parse", "feature/x") == before


def test_pull_reports_dirty_repo_and_still_rebases_the_others(app_layout, tmp_path):
    dep_path, island, a, dep = _island_with_local_work(app_layout, tmp_path)
    a_before = _out(a, "rev-parse", "HEAD")
    _advance_source(app_layout.repo_path, "a-upstream.txt")
    dep_tip = _advance_source(dep_path, "dep-upstream.txt")
    (a / "wip.txt").write_text("wip")
    app_layout.set_working_dir(str(a))

    assert _pull() == 1

    assert _out(a, "rev-parse", "HEAD") == a_before
    assert _is_ancestor(dep, dep_tip)


def test_pull_leaves_conflicts_for_the_user(app_layout, tmp_path, capfd):
    _app_with_dep(app_layout)
    rc, island = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a = _island_a(app_layout, island)
    _commit(a, "same.txt", "island version")
    _commit(Path(app_layout.repo_path), "same.txt", "source version")
    _git(app_layout.repo_path, "push", "-q")
    app_layout.set_working_dir(str(a))

    assert _pull() == 1

    assert "git rebase --continue" in capfd.readouterr().err


def test_pull_outside_an_island_needs_a_name(app_layout, capfd):
    _app_with_dep(app_layout)

    assert _pull() == 1

    assert "Not inside an island" in capfd.readouterr().err

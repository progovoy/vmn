"""`vmn wt create --carry-changes`: copy uncommitted work into the island."""
from pathlib import Path

from helpers import _init_app, _run_vmn_init, _stamp_app
from island_helpers import _app_with_dep, _create_island, _git, _island_a, _out
from version_stamp.cli.args import parse_user_commands


def test_carry_changes_flag_is_off_by_default():
    assert parse_user_commands(["wt", "create", "app"]).carry_changes is False
    assert parse_user_commands(["wt", "create", "app", "--carry-changes"]).carry_changes


def _dirty(repo):
    repo = Path(repo)
    tracked = next(p for p in repo.iterdir() if p.is_file() and p.name != ".gitignore")
    tracked.write_text("edited in place\n")
    (repo / "staged.txt").write_text("staged")
    _git(repo, "add", "staged.txt")
    (repo / "sub").mkdir()
    (repo / "sub" / "untracked.txt").write_text("untracked")
    return tracked.name


def test_carry_changes_copies_tracked_edits_and_untracked_files(app_layout, tmp_path):
    dep_path, _ = _app_with_dep(app_layout)
    edited_a = _dirty(app_layout.repo_path)
    edited_dep = _dirty(dep_path)

    rc, island = _create_island(app_layout, tmp_path, "feat", "--carry-changes")

    assert rc == 0
    for checkout, edited in ((_island_a(app_layout, island), edited_a), (island / "dep_repo", edited_dep)):
        assert (checkout / edited).read_text() == "edited in place\n"
        assert (checkout / "staged.txt").read_text() == "staged"
        assert (checkout / "sub" / "untracked.txt").read_text() == "untracked"
    # The source checkouts keep their work.
    assert _out(app_layout.repo_path, "status", "--porcelain")
    assert (Path(dep_path) / "sub" / "untracked.txt").exists()


def test_carry_changes_skips_checkouts_not_at_the_source_head(app_layout, tmp_path, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    app_layout.write_file_commit_and_push("test_repo_0", "later.txt", "later")
    _dirty(app_layout.repo_path)
    capfd.readouterr()

    rc, island = _create_island(
        app_layout, tmp_path, "old", "--carry-changes", "-fv", "0.0.1"
    )

    assert rc == 0
    assert "not at the same commit" in capfd.readouterr().err
    assert not (_island_a(app_layout, island) / "staged.txt").exists()


def test_without_the_flag_nothing_is_carried(app_layout, tmp_path):
    _app_with_dep(app_layout)
    _dirty(app_layout.repo_path)

    rc, island = _create_island(app_layout, tmp_path, "feat")

    assert rc == 0
    assert not (_island_a(app_layout, island) / "staged.txt").exists()
    assert _out(_island_a(app_layout, island), "status", "--porcelain") == ""

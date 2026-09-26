"""The two-developer island workflow, end to end through the CLI."""
import json
from pathlib import Path

from helpers import _stamp_app
from island_helpers import _app_with_dep, _commit, _create_island, _git, _island_a, _out
from version_stamp.cli.entry import vmn_run


def test_freeze_then_second_developer_gets_the_same_dep_state(app_layout, tmp_path):
    app = app_layout.app_name
    _app_with_dep(app_layout)

    # Developer 1: island, real branches in both repos, freeze, stamp.
    rc, feat = _create_island(app_layout, tmp_path, "feat")
    assert rc == 0
    a1, dep1 = _island_a(app_layout, feat), feat / "dep_repo"
    _git(dep1, "checkout", "-q", "-b", "feature/b")
    _commit(dep1, "b.txt")
    _git(dep1, "push", "-q", "-u", "origin", "feature/b")
    feature_b_tip = _out(dep1, "rev-parse", "HEAD")
    _git(a1, "checkout", "-q", "-b", "feature/x")
    _git(a1, "push", "-q", "-u", "origin", "feature/x")
    app_layout.set_working_dir(str(a1))

    assert vmn_run(["wt", "freeze", app])[0] == 0

    _git(a1, "add", "-A")
    _git(a1, "commit", "-q", "-m", "freeze deps")
    _git(a1, "push", "-q")
    assert _stamp_app(app, "patch")[0] == 0

    # Developer 2: their own clone of A on feature/x; the dep checkout next
    # to it is still on its default branch.
    clone_a = app_layout.create_new_clone("test_repo_0")
    _git(clone_a, "checkout", "-q", "feature/x")
    app_layout.set_working_dir(clone_a)

    rc, review = _create_island(app_layout, tmp_path, "review")

    assert rc == 0
    a2 = review / Path(clone_a).name
    dep2 = review / "dep_repo"
    assert _out(dep2, "rev-parse", "HEAD") == feature_b_tip
    assert _out(dep2, "branch", "--show-current") == "island/review/feature/b"
    manifest = json.loads((review / "island.json").read_text())
    assert manifest["main_repo"]["source_branch"] == "feature/x"
    assert manifest["deps"]["dep_repo"]["source_branch"] == "feature/b"

    # Developer 1 moves feature/b on; developer 2 pulls it in.
    _commit(dep1, "b2.txt")
    _git(dep1, "push", "-q")
    app_layout.set_working_dir(str(a2))

    assert vmn_run(["wt", "pull"])[0] == 0

    assert _out(dep2, "rev-parse", "HEAD") == _out(dep1, "rev-parse", "HEAD")

"""What `vmn goto` reports for each dependency repo it updates."""
from helpers import _configure_2_deps, _goto, _init_app, _run_vmn_init, _stamp_app


def _head(app_layout, repo):
    return app_layout._repos[repo]["_be"].be.changeset()


def _two_versions_moving_repo1(app_layout):
    """0.0.2 and 0.0.3 differ only in repo1's commit; returns both repo1 heads."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    old = _head(app_layout, "repo1")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg2")
    assert _stamp_app(app_layout.app_name, "patch")[0] == 0
    return old, _head(app_layout, "repo1")


def _goto_output(capfd, app_name, version=None):
    capfd.readouterr()
    assert _goto(app_name, version=version) == 0
    return capfd.readouterr().out


def test_goto_reports_unchanged_dep_as_already_at(app_layout, capfd):
    _two_versions_moving_repo1(app_layout)
    repo2_head = _head(app_layout, "repo2")

    out = _goto_output(capfd, app_layout.app_name, version="0.0.2")

    assert f"../repo2 is already at changeset {repo2_head[:8]} ({repo2_head[:8]})" in out
    assert "Updated ../repo2" not in out


def test_goto_version_reports_moved_dep_old_to_new(app_layout, capfd):
    old, new = _two_versions_moving_repo1(app_layout)

    out = _goto_output(capfd, app_layout.app_name, version="0.0.2")

    assert f"Updated ../repo1 to changeset {old[:8]} ({new[:8]} -> {old[:8]})" in out


def test_goto_branch_tip_reports_moved_dep_old_to_new(app_layout, capfd):
    old, new = _two_versions_moving_repo1(app_layout)
    assert _goto(app_layout.app_name, version="0.0.2") == 0

    out = _goto_output(capfd, app_layout.app_name)

    branch = app_layout._repos["repo1"]["_be"].be.get_active_branch()
    assert f"Updated ../repo1 to branch {branch} ({old[:8]} -> {new[:8]})" in out


def test_goto_does_not_log_updating_at_info(app_layout, capfd):
    _two_versions_moving_repo1(app_layout)

    out = _goto_output(capfd, app_layout.app_name, version="0.0.2")

    assert "Updating" not in out

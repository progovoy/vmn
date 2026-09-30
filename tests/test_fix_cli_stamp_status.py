"""handle_stamp / _get_repo_status / _init_app fixes."""
import os
from types import SimpleNamespace

import pytest
from helpers import _init_app, _run_vmn_init, _stamp_app
from version_stamp.cli import commands
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from version_stamp.stamping.publisher import VersionControlStamper


def _stamped_app(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    return params


def test_footer_breaking_change_stamps_major(app_layout, capfd):
    params = _stamped_app(app_layout)
    app_layout.write_conf(params["app_conf_path"], conventional_commits=True)
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "f1.txt",
        "text",
        commit_msg="feat: x\n\nsome body\n\nBREAKING CHANGE: y",
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "1.0.0"


class _FakeDepBackend:
    def __init__(self, branch):
        self._branch = branch

    def check_for_pending_changes(self):
        return 0

    def check_for_outgoing_changes(self):
        return 0

    def get_active_branch(self):
        if self._branch is None:
            raise RuntimeError("Failed to find remote branch for hex: abc")
        return self._branch

    def in_detached_head(self):
        return self._branch is None


def _fake_vcs(tmp_path):
    deps = {"../repo1": {"branch": "main"}, "../repo2": {"branch": "main"}}
    return SimpleNamespace(
        backend=SimpleNamespace(
            check_for_pending_changes=lambda: 0,
            check_for_outgoing_changes=lambda: 0,
        ),
        tracked=True,
        current_version_info={"stamping": {"app": {"name": "app"}}},
        verstr_from_file="0.0.1",
        find_matching_version=lambda verstr: {},
        configured_deps=deps,
        actual_deps_state=dict(deps),
        vmn_root_path=str(tmp_path),
        be_type=None,
        name="app",
    )


def test_branch_pinned_dep_on_no_branch_names_the_repo(tmp_path, monkeypatch):
    """A dep whose active branch can't be resolved is reported by its own name,
    whatever order the deps are checked in."""
    backends = {"repo1": _FakeDepBackend("main"), "repo2": _FakeDepBackend(None)}
    monkeypatch.setattr(
        commands,
        "get_client",
        lambda path, be_type: (backends[os.path.basename(path)], None),
    )

    status = commands._get_repo_status(
        _fake_vcs(tmp_path), {"deps_synced_with_conf"}, {"detached"}
    )

    assert status.error
    msg = status.err_msgs["deps_synced_with_conf"]
    assert "../repo2" in msg
    assert "../repo1" not in msg
    assert status.repos["../repo2"]["branch_synced_error"]
    assert "not_synced_with_conf" not in status.repos["../repo1"]["state"]


def test_init_app_publish_failure_returns_1(app_layout, capfd, monkeypatch):
    _run_vmn_init()

    def _fail(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(VersionControlStamper, "publish_stamp", _fail)
    capfd.readouterr()
    reset_logger()
    err, _ = vmn_run(["init-app", "-v", "0.0.0", app_layout.app_name])
    captured = capfd.readouterr()

    assert err == 1
    assert "Failed to init app" in captured.err
    assert "vmn_run raised exception" not in captured.err


@pytest.mark.parametrize("override", ["5", "abc"])
def test_stamp_rejects_invalid_override_cleanly(app_layout, capfd, override):
    _stamped_app(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "text")

    capfd.readouterr()
    err, _, _ = _stamp_app(app_layout.app_name, "patch", override_version=override)
    captured = capfd.readouterr()

    assert err == 1
    assert "vmn_run raised exception" not in captured.err
    assert "Version must be in format" in captured.err

import os

import yaml

from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger

from helpers import (
    _configure_2_deps,
    _configure_empty_conf,
    _init_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_conf(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "text")

    conf = {
        "deps": {
            "../": {
                "test_repo_0": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
        "extra_info": False,
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_empty_conf(app_layout, params)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = _configure_2_deps(app_layout, params)
    conf["deps"]["../"]["repo1"]["branch"] = "new_branch"
    conf["deps"]["../"]["repo2"]["hash"] = "deadbeef"
    app_layout.write_conf(params["app_conf_path"], **conf)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    capfd.readouterr()

    app_layout.checkout("new_branch", repo_name="repo1", create_new=True)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    conf["deps"]["../"]["repo2"]["hash"] = app_layout._repos["repo2"][
        "_be"
    ].be.changeset()
    app_layout.write_conf(params["app_conf_path"], **conf)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    captured = capfd.readouterr()
    assert captured.out == "[INFO] 0.0.4\n"


def test_conf_for_branch(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    branch = "b2"
    app_layout.write_conf(
        f"{app_layout.repo_path}/.vmn/{app_layout.app_name}/{branch}_conf.yml",
        template="[test_{major}][.{minor}][.{patch}]",
    )

    capfd.readouterr()
    _show(app_layout.app_name)
    captured = capfd.readouterr()

    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"

    import subprocess

    base_cmd = ["git", "checkout", "-b", branch]
    subprocess.call(base_cmd, cwd=app_layout.repo_path)

    capfd.readouterr()
    _show(app_layout.app_name)
    captured = capfd.readouterr()

    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "test_0.0.1"


def test_conf_for_branch_removal_of_conf(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()
    branch = "b2"
    branch_conf_path = os.path.join(
        f"{app_layout.repo_path}",
        ".vmn",
        f"{app_layout.app_name}",
        f"{branch}_conf.yml",
    )
    app_layout.write_conf(
        branch_conf_path, template="[test_{major}][.{minor}][.{patch}]"
    )

    assert os.path.exists(branch_conf_path)

    import subprocess

    base_cmd = ["git", "checkout", "-b", branch]
    subprocess.call(base_cmd, cwd=app_layout.repo_path)

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "a.txt",
        "bv",
    )

    err, ver_info, params = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    assert os.path.exists(branch_conf_path)

    base_cmd = ["git", "checkout", main_branch]
    subprocess.call(base_cmd, cwd=app_layout.repo_path)

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "b.txt",
        "bv",
    )

    assert os.path.exists(branch_conf_path)

    err, ver_info, params = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    assert not os.path.exists(branch_conf_path)


def test_config_list_apps(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config"])[0]
    captured = capfd.readouterr()

    assert ret == 0
    assert app_layout.app_name in captured.out


def test_config_list_apps_empty(app_layout, capfd):
    _run_vmn_init()

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config"])[0]
    captured = capfd.readouterr()

    assert ret == 0
    assert "No managed apps found" in captured.out


def test_config_no_tty(app_layout, capfd):
    """Interactive mode should fail when stdin is not a TTY."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config", app_layout.app_name])[0]
    captured = capfd.readouterr()

    assert ret == 1
    assert "terminal" in captured.err.lower() or "terminal" in captured.out.lower()


def test_config_no_app(app_layout, capfd):
    """Config for non-existent app should error."""
    _run_vmn_init()

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config", "nonexistent_app"])[0]

    assert ret == 1


def test_config_interactive_save(app_layout, capfd, monkeypatch):
    """Test interactive mode: change hide_zero_hotfix, then save."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    # Mock questionary interactions:
    # 1st select: pick "hide_zero_hotfix" key
    # 2nd confirm: set to False
    # 3rd select: pick "Save & quit"
    import questionary as q

    call_count = {"select": 0, "confirm": 0}
    original_select = q.select
    original_confirm = q.confirm

    class FakeResult:
        def __init__(self, val):
            self._val = val
        def ask(self):
            return self._val

    def mock_select(message, choices=None, **kwargs):
        call_count["select"] += 1
        if call_count["select"] == 1:
            # Pick hide_zero_hotfix
            return FakeResult("hide_zero_hotfix")
        else:
            # Save & quit
            return FakeResult("_save")

    def mock_confirm(message, **kwargs):
        call_count["confirm"] += 1
        # Set hide_zero_hotfix to False
        return FakeResult(False)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(q, "select", mock_select)
    monkeypatch.setattr(q, "confirm", mock_confirm)

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config", app_layout.app_name])[0]
    captured = capfd.readouterr()

    assert ret == 0
    assert "saved" in captured.out.lower() or "Saved" in captured.out

    # Verify the conf.yml was actually updated
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path, "r") as f:
        data = yaml.safe_load(f)

    assert data["conf"]["hide_zero_hotfix"] is False


def test_config_interactive_quit_no_save(app_layout, capfd, monkeypatch):
    """Test interactive mode: quit without saving preserves original config."""
    _run_vmn_init()
    _init_app(app_layout.app_name)

    import questionary as q

    class FakeResult:
        def __init__(self, val):
            self._val = val
        def ask(self):
            return self._val

    select_count = {"n": 0}

    def mock_select(message, choices=None, **kwargs):
        select_count["n"] += 1
        return FakeResult("_quit")

    def mock_confirm(message, **kwargs):
        # No unsaved changes, so this shouldn't be called,
        # but return True (discard) just in case
        return FakeResult(True)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(q, "select", mock_select)
    monkeypatch.setattr(q, "confirm", mock_confirm)

    # Read original config
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path, "r") as f:
        original_data = yaml.safe_load(f)

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config", app_layout.app_name])[0]

    assert ret == 0

    # Config should be unchanged
    with open(conf_path, "r") as f:
        after_data = yaml.safe_load(f)

    assert original_data == after_data


def test_config_global(app_layout, capfd, monkeypatch):
    """Test --global flag targets .vmn/conf.yml."""
    _run_vmn_init()

    import questionary as q

    class FakeResult:
        def __init__(self, val):
            self._val = val
        def ask(self):
            return self._val

    def mock_select(message, choices=None, **kwargs):
        return FakeResult("_quit")

    def mock_confirm(message, **kwargs):
        return FakeResult(True)

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(q, "select", mock_select)
    monkeypatch.setattr(q, "confirm", mock_confirm)

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config", "--global"])[0]

    assert ret == 0

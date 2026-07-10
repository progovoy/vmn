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
    app_dir = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name
    )
    flat_conf_path = os.path.join(app_dir, f"{branch}_conf.yml")
    canonical_conf_path = os.path.join(
        app_dir, "branch_conf", branch, "conf.yml"
    )
    app_layout.write_conf(
        flat_conf_path, template="[test_{major}][.{minor}][.{patch}]"
    )

    assert os.path.exists(flat_conf_path)

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

    # Stamping on the branch migrates its flat conf to the canonical layout.
    assert not os.path.exists(flat_conf_path)
    assert os.path.exists(canonical_conf_path)

    base_cmd = ["git", "checkout", main_branch]
    subprocess.call(base_cmd, cwd=app_layout.repo_path)

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "b.txt",
        "bv",
    )

    # The canonical conf was committed on b2, so on main only the original
    # flat b2 conf (committed here before the branch) is present.
    assert os.path.exists(flat_conf_path)
    assert not os.path.exists(canonical_conf_path)

    err, ver_info, params = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    # Stamping on main migrates b2's flat conf then removes it as an
    # other-branch conf, leaving no branch_conf layout behind.
    assert not os.path.exists(flat_conf_path)
    assert not os.path.exists(canonical_conf_path)
    assert not os.path.isdir(os.path.join(app_dir, "branch_conf"))


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


def _active_branch(app_layout):
    return app_layout._app_backend.be.get_active_branch()


# ── Cycle 3: --branch targets canonical path, seeded from effective conf ──


def test_config_branch_vim_creates_canonical_conf(app_layout, monkeypatch):
    from version_stamp.core.utils import branch_conf_canonical_path

    _run_vmn_init()
    _init_app(app_layout.app_name)

    monkeypatch.setenv("EDITOR", "true")

    reset_logger()
    ret = vmn_run(["config", app_layout.app_name, "--branch", "--vim"])[0]
    assert ret == 0

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical = branch_conf_canonical_path(app_dir, _active_branch(app_layout))
    assert os.path.isfile(canonical)


def test_config_branch_vim_seeds_from_existing_flat_conf(app_layout, monkeypatch):
    from version_stamp.core.utils import (
        branch_conf_canonical_path,
        branch_conf_flat_path,
    )

    _run_vmn_init()
    _init_app(app_layout.app_name)

    branch = _active_branch(app_layout)
    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    flat = branch_conf_flat_path(app_dir, branch)
    app_layout.write_conf(flat, template="[{major}].[{minor}]")

    with open(flat, "r") as f:
        flat_data = yaml.safe_load(f)

    monkeypatch.setenv("EDITOR", "true")

    reset_logger()
    ret = vmn_run(["config", app_layout.app_name, "--branch", "--vim"])[0]
    assert ret == 0

    canonical = branch_conf_canonical_path(app_dir, branch)
    assert os.path.isfile(canonical)
    with open(canonical, "r") as f:
        canonical_data = yaml.safe_load(f)

    assert canonical_data["conf"] == flat_data["conf"]
    # flat left in place
    assert os.path.isfile(flat)


def test_config_branch_root_vim_creates_canonical_root_conf(app_layout, monkeypatch):
    from version_stamp.core.utils import branch_conf_canonical_path

    root_app_name = "root_app/service1"
    _run_vmn_init()
    _init_app(root_app_name)

    monkeypatch.setenv("EDITOR", "true")

    reset_logger()
    ret = vmn_run(["config", root_app_name, "--branch", "--root", "--vim"])[0]
    assert ret == 0

    root_app_dir = os.path.join(app_layout.repo_path, ".vmn", "root_app")
    canonical = branch_conf_canonical_path(
        root_app_dir, _active_branch(app_layout), root=True
    )
    assert os.path.isfile(canonical)


# ── Cycle 4: listing prunes branch_conf, reserved app name ──


def test_config_list_apps_ignores_branch_conf_dirs(app_layout, capfd):
    from version_stamp.core.utils import branch_conf_canonical_path

    _run_vmn_init()
    _init_app(app_layout.app_name)

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical = branch_conf_canonical_path(app_dir, _active_branch(app_layout))
    os.makedirs(os.path.dirname(canonical), exist_ok=True)
    app_layout.write_conf(canonical, template="[{major}]")

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["config"])[0]
    captured = capfd.readouterr()

    assert ret == 0
    assert app_layout.app_name in captured.out
    assert "branch_conf" not in captured.out


def test_init_app_rejects_branch_conf_app_name(app_layout, capfd):
    _run_vmn_init()

    capfd.readouterr()
    reset_logger()
    ret = vmn_run(["init-app", "my_app/branch_conf/foo"])[0]

    assert ret == 1


# ── Cycle 6: vmn config gen (non-interactive) ──


def test_config_gen_arg_parsing():
    from version_stamp.cli.args import parse_user_commands

    args = parse_user_commands(["config", "gen", "x"])
    assert args.gen is True
    assert args.name == "x"

    args = parse_user_commands(["config", "x"])
    assert args.gen is False
    assert args.name == "x"

    args = parse_user_commands(["config", "gen"])
    assert args.gen is True
    assert args.name is None


def test_config_gen_creates_default_conf(app_layout):
    import dataclasses
    from version_stamp.core.models import AppConf

    _run_vmn_init()

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name])[0]
    assert ret == 0

    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    assert os.path.isfile(conf_path)
    with open(conf_path, "r") as f:
        data = yaml.safe_load(f)

    assert data["conf"] == dataclasses.asdict(AppConf())


def test_config_gen_existing_file_errors(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name])[0]
    assert ret == 1


def test_config_gen_branch_seeds_from_existing_conf(app_layout):
    from version_stamp.core.utils import branch_conf_canonical_path

    _run_vmn_init()
    _init_app(app_layout.app_name)

    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path, "r") as f:
        default_conf = yaml.safe_load(f)["conf"]

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name, "--branch"])[0]
    assert ret == 0

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical = branch_conf_canonical_path(app_dir, _active_branch(app_layout))
    assert os.path.isfile(canonical)
    with open(canonical, "r") as f:
        canonical_conf = yaml.safe_load(f)["conf"]

    assert canonical_conf == default_conf


def test_config_gen_branch_existing_canonical_errors(app_layout):
    from version_stamp.core.utils import branch_conf_canonical_path

    _run_vmn_init()
    _init_app(app_layout.app_name)

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical = branch_conf_canonical_path(app_dir, _active_branch(app_layout))
    os.makedirs(os.path.dirname(canonical), exist_ok=True)
    app_layout.write_conf(canonical, template="[{major}]")

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name, "--branch"])[0]
    assert ret == 1


def test_config_gen_root_branch(app_layout):
    from version_stamp.core.utils import branch_conf_canonical_path

    root_app_name = "root_app/service1"
    _run_vmn_init()
    _init_app(root_app_name)

    reset_logger()
    ret = vmn_run(
        ["config", "gen", root_app_name, "--branch", "--root"]
    )[0]
    assert ret == 0

    root_app_dir = os.path.join(app_layout.repo_path, ".vmn", "root_app")
    canonical = branch_conf_canonical_path(
        root_app_dir, _active_branch(app_layout), root=True
    )
    assert os.path.isfile(canonical)


def test_config_gen_requires_app_name(app_layout):
    _run_vmn_init()

    reset_logger()
    ret = vmn_run(["config", "gen"])[0]
    assert ret == 1


def test_config_gen_root_on_plain_app_errors(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)  # single-segment app, not a root app

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name, "--root"])[0]
    assert ret == 1

    root_conf = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "root_conf.yml"
    )
    assert not os.path.exists(root_conf)

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name, "--branch", "--root"])[0]
    assert ret == 1


def test_config_gen_creates_default_conf_when_branch_conf_exists(app_layout):
    from version_stamp.core.utils import branch_conf_canonical_path

    _run_vmn_init()
    _init_app(app_layout.app_name)

    app_dir = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name)
    canonical = branch_conf_canonical_path(app_dir, _active_branch(app_layout))
    os.makedirs(os.path.dirname(canonical), exist_ok=True)
    app_layout.write_conf(canonical, template="[{major}]")

    # Default gen targets conf.yml itself, not the branch-resolved conf.
    conf_path = os.path.join(app_dir, "conf.yml")
    os.remove(conf_path)

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name])[0]
    assert ret == 0
    assert os.path.isfile(conf_path)


def test_config_gen_works_without_tty(app_layout, monkeypatch):
    _run_vmn_init()

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    reset_logger()
    ret = vmn_run(["config", "gen", app_layout.app_name])[0]
    assert ret == 0

    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    assert os.path.isfile(conf_path)

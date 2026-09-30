"""IVersionsStamper fixes: a missing conf.yml still gets a parsed template,
``hide_zero_hotfix: false`` tags are looked up under the names they are
written with, and a root app's conf dir is created for its own path."""
import os
import subprocess

import yaml
from helpers import (
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
    reset_logger,
    vmn_run,
)


def _conf_path(app_layout, app_name):
    return os.path.join(app_layout.repo_path, ".vmn", app_name, "conf.yml")


def _set_conf(app_layout, app_name, **conf):
    path = _conf_path(app_layout, app_name)
    with open(path) as f:
        data = yaml.safe_load(f)
    data["conf"].update(conf)
    with open(path, "w") as f:
        yaml.dump(data, f)
    app_layout._app_backend.add_conf_file(path)


def _commit_change(app_layout, content):
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", content)


def _tags(app_layout):
    out = subprocess.run(
        ["git", "tag", "-l"],
        cwd=app_layout.repo_path, check=True, capture_output=True, text=True,
    ).stdout
    return set(out.split())


def _stamped(app_name, **kwargs):
    err, ver_info, _ = _stamp_app(app_name, **kwargs)
    assert err == 0
    return ver_info["stamping"]["app"]["_version"]


def test_stamp_and_show_work_after_conf_file_is_deleted(app_layout, capfd):
    app = app_layout.app_name
    _run_vmn_init()
    _init_app(app)
    assert _stamped(app, release_mode="patch") == "0.0.1"

    app_layout.remove_file(_conf_path(app_layout, app))

    capfd.readouterr()
    assert _stamped(app, release_mode="patch") == "0.0.2"
    assert "0.0.2" in capfd.readouterr().out

    assert _show(app) == 0
    assert capfd.readouterr().out == "0.0.2\n"


def test_zero_hotfix_prerelease_counter_and_release(app_layout, capfd):
    app = app_layout.app_name
    _run_vmn_init()
    _init_app(app)
    _set_conf(app_layout, app, hide_zero_hotfix=False)

    assert _stamped(app, release_mode="patch", prerelease="rc") == "0.0.1.0-rc.1"
    for n in (2, 3):
        _commit_change(app_layout, f"rc{n}")
        assert _stamped(app, prerelease="rc") == f"0.0.1.0-rc.{n}"
    _commit_change(app_layout, "beta")
    assert _stamped(app, prerelease="beta") == "0.0.1.0-beta.1"
    _commit_change(app_layout, "rc4")
    assert _stamped(app, prerelease="rc") == "0.0.1.0-rc.4"

    # nothing changed: the same version is matched instead of a new rc
    assert _stamped(app, prerelease="rc") == "0.0.1.0-rc.4"
    assert f"{app}_0.0.1.0-rc.5" not in _tags(app_layout)

    err, _, _ = _release_app(app, "0.0.1.0-rc.4")
    assert err == 0
    tags = _tags(app_layout)
    assert f"{app}_0.0.1.0" in tags
    assert f"{app}_0.0.1" not in tags

    capfd.readouterr()
    err, _, _ = _release_app(app, "0.0.1.0-rc.4")
    assert err == 0
    assert "0.0.1.0" in capfd.readouterr().out
    assert f"{app}_0.0.1" not in _tags(app_layout)


def test_root_conf_dir_is_created_for_the_root_conf_path(app_layout, tmp_path):
    app = "root_app/app1"
    _run_vmn_init()
    _init_app(app)

    reset_logger()
    _, vmn_ctx = vmn_run(["show", app])
    vcs = vmn_ctx.vcs
    vcs.root_conf_file_exists = False
    vcs.root_app_conf_path = str(tmp_path / "elsewhere" / "root_conf.yml")

    vcs.create_config_files()

    assert os.path.isfile(vcs.root_app_conf_path)

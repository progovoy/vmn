"""A conf file with a bare `conf:` (YAML null) or no `conf` key reads as empty."""
import os

import pytest
import yaml

from helpers import _init_app, _run_vmn_init, _show, _stamp_app
from version_stamp.cli.config_tui import _read_raw_conf


def _stamped(app_layout, app_name):
    _run_vmn_init()
    _init_app(app_name)
    err, _, params = _stamp_app(app_name, "patch")
    assert err == 0
    return params


def _commit(app_layout, path, text):
    with open(path, "w") as f:
        f.write(text)
    app_layout.git_cmd(args=["add", path])
    app_layout.git_cmd(args=["commit", "-m", "update conf"])
    app_layout.git_cmd(args=["push"])


def _change(app_layout):
    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "change")


@pytest.mark.parametrize("text", ["conf:\n", "other: 1\n", ""])
def test_app_conf_without_a_conf_mapping_reads_as_empty(app_layout, capfd, text):
    params = _stamped(app_layout, app_layout.app_name)
    _commit(app_layout, params["app_conf_path"], text)

    capfd.readouterr()
    assert _show(app_layout.app_name) == 0
    assert "0.0.1" in capfd.readouterr().out

    _change(app_layout)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


@pytest.mark.parametrize("text", ["conf:\n", "other: 1\n", ""])
def test_root_conf_without_a_conf_mapping_reads_as_empty(app_layout, capfd, text):
    _stamped(app_layout, "root_app/service1")
    root_conf = os.path.join(app_layout.repo_path, ".vmn", "root_app", "root_conf.yml")
    _commit(app_layout, root_conf, text)

    capfd.readouterr()
    assert _show("root_app/service1") == 0
    assert "0.0.1" in capfd.readouterr().out

    _change(app_layout)
    assert _stamp_app("root_app/service1", "patch")[0] == 0


@pytest.mark.parametrize("text", ["conf:\n", "other: 1\n", ""])
def test_config_tui_reads_a_conf_without_a_conf_mapping_as_empty(tmp_path, text):
    path = tmp_path / "conf.yml"
    path.write_text(text)

    assert _read_raw_conf(str(path)) == {}


def test_a_conf_mapping_is_still_read(tmp_path):
    path = tmp_path / "conf.yml"
    path.write_text(yaml.dump({"conf": {"template": "[{major}]"}}))

    assert _read_raw_conf(str(path)) == {"template": "[{major}]"}

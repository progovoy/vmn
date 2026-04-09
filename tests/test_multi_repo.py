import copy
import os
import shutil

import yaml

from helpers import (
    _configure_2_deps,
    _goto,
    _init_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_multi_repo_dependency(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = _configure_2_deps(app_layout, params)

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1", commit=False)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    captured = capfd.readouterr()
    assert "[ERROR] \nPending changes in" in captured.err
    assert "repo1" in captured.err
    app_layout.revert_changes("repo1")

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1", push=False)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    captured = capfd.readouterr()
    assert "[ERROR] \nOutgoing changes in" in captured.err
    assert "repo1" in captured.err
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"

    assert "." in ver_info["stamping"]["app"]["changesets"]
    assert os.path.join("..", "repo1") in ver_info["stamping"]["app"]["changesets"]
    assert os.path.join("..", "repo2") in ver_info["stamping"]["app"]["changesets"]

    # TODO:: remove this line (seems like the conf write is redundant
    app_layout.write_conf(params["app_conf_path"], **conf)

    with open(params["app_conf_path"], "r") as f:
        data = yaml.safe_load(f)
        assert "../" in data["conf"]["deps"]
        assert "test_repo_0" in data["conf"]["deps"]["../"]
        assert "repo1" in data["conf"]["deps"]["../"]
        assert "repo2" in data["conf"]["deps"]["../"]

    conf["deps"]["../"]["repo3"] = copy.deepcopy(conf["deps"]["../"]["repo2"])
    conf["deps"]["../"]["repo3"].pop("remote")

    app_layout.write_conf(params["app_conf_path"], **conf)
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1

    err = _goto(app_layout.app_name)
    assert err == 1

    app_layout.create_repo(repo_name="repo3", repo_type="git")

    err = _goto(app_layout.app_name)
    assert err == 0

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err = _goto(app_layout.app_name)
    assert err == 0

    shutil.rmtree(app_layout._repos["repo3"]["path"])

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    captured = capfd.readouterr()
    assert captured.out == "dirty:\n- version_not_matched\nout: 0.0.3\n\n"

    err = _goto(app_layout.app_name)
    assert err == 0


def test_multi_repo_dependency_goto_and_stamp(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    prev_ver = ver_info["stamping"]["app"]["_version"]

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert prev_ver != ver_info["stamping"]["app"]["_version"]

    err = _goto(app_layout.app_name, version=prev_ver)
    assert err == 0

    # TODO:: for each stamp add capfd assertions
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == prev_ver


def test_multi_repo_dependency_goto_and_show(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    prev_ver = ver_info["stamping"]["app"]["_version"]

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert prev_ver != ver_info["stamping"]["app"]["_version"]

    err = _goto(app_layout.app_name, version=prev_ver)
    assert err == 0

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    captured = capfd.readouterr()
    assert captured.out == "0.0.2\n"


def test_multi_repo_dependency_on_specific_branch_goto(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params, specific_branch="new_branch")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

    capfd.readouterr()
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    captured = capfd.readouterr()

    err = _goto(app_layout.app_name)
    assert err == 0
    captured = capfd.readouterr()

    err = _show(app_layout.app_name)
    assert err == 0
    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    captured = capfd.readouterr()

    err = _show(app_layout.app_name)
    assert err == 0
    captured = capfd.readouterr()
    assert captured.out == "0.0.2\n"


def test_no_fetch_branch_configured_for_deps(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, _, params = _stamp_app(app_layout.app_name, "minor")

    capfd.readouterr()

    _configure_2_deps(app_layout, params)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    app_layout.git_cmd("repo1", ["config", "--unset", "remote.origin.fetch"])

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

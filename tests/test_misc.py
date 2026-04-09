import os
import shutil
import subprocess
import time

import filelock
import yaml

from version_stamp.backends.base import VMNBackend
from version_stamp.cli.constants import VER_FILE_NAME
from version_stamp.cli.entry import vmn_run
from version_stamp.core.logging import reset_logger
from version_stamp.stamping.base import IVersionsStamper

from helpers import (
    _add_buildmetadata_to_version,
    _configure_2_deps,
    _goto,
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_version_template():
    formated_version = VMNBackend.get_utemplate_formatted_version(
        "2.0.9", IVersionsStamper.parse_template("[{major}][-{prerelease}]"), True
    )

    assert formated_version == "2"

    formated_version = VMNBackend.get_utemplate_formatted_version(
        "2.0.9.0", IVersionsStamper.parse_template("[{major}][-{hotfix}]"), True
    )

    assert formated_version == "2"

    formated_version = VMNBackend.get_utemplate_formatted_version(
        "2.0.9.0", IVersionsStamper.parse_template("[{major}][-{hotfix}]"), False
    )

    assert formated_version == "2-0"


def test_get_version(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("new_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout._app_backend.be.checkout(main_branch)
    app_layout.merge(from_rev="new_branch", to_rev=main_branch, squash=True)
    app_layout._app_backend.selected_remote.pull(rebase=True)
    app_layout._app_backend.be.push()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"


def test_get_version_number_from_file(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name, "0.2.1-rc.1")

    with open(params["version_file_path"], "r") as fid:
        ver_dict = yaml.load(fid, Loader=yaml.FullLoader)

    assert "0.2.1-rc.1" == ver_dict["version_to_stamp_from"]


def test_read_version_from_file(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    app_layout._app_backend.selected_remote.pull(rebase=True)

    with open(file_path, "r") as fid:
        ver_dict = yaml.load(fid, Loader=yaml.FullLoader)

    assert "0.2.1" == ver_dict["version_to_stamp_from"]


def test_manual_file_adjustment(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": "0.2.3",
        "prerelease": "release",
        "prerelease_count": {},
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        ".vmn/test_app/{}".format(VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "0.2.4" == _version


def test_manual_file_adjustment_with_major_version(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": "1.2.3",
        "prerelease": "release",
        "prerelease_count": {},
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        ".vmn/test_app/{}".format(VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "1.2.4" == _version


def test_manual_file_adjustment_rc(app_layout):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name, "0.2.1-rc.5")

    err, ver_info, _ = _stamp_app(app_layout.app_name, optional_release_mode="patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "0.2.1-rc.6" == _version

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": "0.2.3-alpha9.9",
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        ".vmn/test_app/{}".format(VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, optional_release_mode="patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "0.2.3-alpha9.10" == _version


def test_remotes(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    import subprocess

    cmds = [
        ["git", "remote", "add", "or2", app_layout.repo_path],
        ["git", "remote", "rename", "origin", "or3"],
        ["git", "remote", "rename", "or2", "origin"],
        ["git", "remote", "remove", "or3"],
        ["git", "remote", "add", "or3", app_layout.repo_path],
        ["git", "remote", "remove", "origin"],
        ["git", "remote", "add", "or2", f"{app_layout.repo_path}2"],
    ]
    c = 2
    for cmd in cmds:
        subprocess.call(cmd, cwd=app_layout.repo_path)

        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == f"0.0.{c}"
        c += 1


def test_add_bm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        url="https://whateverlink.com",
    )
    assert err == 0

    # TODO assert matching version

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "file.txt",
        "str1",
    )

    captured = capfd.readouterr()
    assert not captured.err

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-not-okay",
        url="https://whateverlink.com",
    )
    assert err == 1

    captured = capfd.readouterr()
    assert (
        "[ERROR] When running vmn add and not on a version commit, "
        "you must specify a specific version using -v flag\n" in captured.err
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.2",
        url="https://whateverlink.com",
    )
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.2\n" == captured.out

    err = _show(app_layout.app_name, raw=True, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    assert len(yaml.safe_load(captured.out)["versions"]) == 2

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "file.txt",
        "str1",
    )

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.2",
        url="https://whateverlink.com",
    )
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay2",
        version="0.0.2",
        url="https://whateverlink.com",
    )
    assert err == 0

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True, verbose=True, version="0.0.2")
    assert err == 0

    captured = capfd.readouterr()
    assert len(yaml.safe_load(captured.out)["versions"]) == 3

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.3",
        url="https://whateverlink.com",
    )
    assert err == 1

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="999.999.999",
        url="https://whateverlink.com",
    )
    assert err == 1

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.3",
        url="https://whateverlink.com",
    )
    assert err == 0

    capfd.readouterr()
    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay+",
        version="0.0.3",
        url="https://whateverlink.com",
    )
    assert err == 1

    captured = capfd.readouterr()
    assert (
        "[ERROR] Tag test_app_0.0.3+build.1-aef.1-its-okay+ "
        "doesn't comply " in captured.err
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.yml",
        yaml.dump({"build_flags": "-g", "build_time": "Debug"}),
        commit=False,
    )

    for i in range(2):
        err = _add_buildmetadata_to_version(
            app_layout,
            "build.1-aef.1-its-okay3",
            version="0.0.3",
            file_path="test.yml",
            url="https://whateverlink.com",
        )
        assert err == 0
        app_layout.write_file_commit_and_push(
            "test_repo_0",
            "test.yml",
            yaml.dump({"build_flags": "-g", "build_time": "Debug"}),
            commit=False,
        )

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.yml",
        yaml.dump({"build_flags": "-g2", "build_time": "Debug"}),
        commit=False,
    )

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay3",
        version="0.0.3",
        file_path="test.yml",
        url="https://whateverlink.com",
    )
    assert err == 1

    capfd.readouterr()
    err = _show(
        app_layout.app_name,
        raw=True,
        version="0.0.3+build.1-aef.1-its-okay3",
        verbose=True,
    )
    assert err == 0

    captured = capfd.readouterr()
    assert len(yaml.safe_load(captured.out)["versions"]) == 3
    assert yaml.safe_load(captured.out)["version_metadata"]["build_flags"] == "-g"
    assert yaml.safe_load(captured.out)["versions"][0] == "0.0.3"

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.tst",
        "bla",
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch", prerelease="alpha")
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.4-alpha.1",
        url="https://whateverlink.com",
    )
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.test",
        yaml.dump(
            {
                "bla": "-g2",
            }
        ),
    )

    err, ver_info, _ = _release_app(app_layout.app_name, "0.0.4-alpha.1")
    assert err == 0


def test_perf_show(app_layout):
    import time
    import filelock

    cache_dir = "/tmp/vmn_perf_repo"
    cache_remote = os.path.join(cache_dir, "test_repo_remote")
    lock_path = f"{cache_dir}.lock"

    cache_valid = os.path.isfile(os.path.join(cache_remote, "HEAD"))
    if not cache_valid:
        shutil.rmtree(cache_dir, ignore_errors=True)
        with filelock.FileLock(lock_path):
            if not os.path.isfile(os.path.join(cache_remote, "HEAD")):
                _run_vmn_init()
                _init_app(app_layout.app_name)

                for i in range(200):
                    app_layout.write_file_commit_and_push(
                        "test_repo_0", f"file_{i}.txt", f"change {i}"
                    )
                    reset_logger()
                    err, _, _ = _stamp_app(app_layout.app_name, "patch")
                    assert err == 0

                os.makedirs(cache_dir, exist_ok=True)
                shutil.copytree(app_layout.test_app_remote, cache_remote)

    shutil.rmtree(app_layout.repo_path)
    subprocess.call(
        ["git", "clone", cache_remote, app_layout.repo_path],
        cwd=app_layout.base_dir,
    )
    app_layout.set_working_dir(app_layout.repo_path)

    t1 = time.perf_counter()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0
    t2 = time.perf_counter()
    diff = t2 - t1

    assert diff < 10


def test_run_vmn_from_non_git_repo(app_layout, capfd):
    _run_vmn_init()
    app_layout.set_working_dir(app_layout.base_dir)
    reset_logger()
    capfd.readouterr()
    ret = vmn_run([])[0]
    capfd.readouterr()
    assert ret == 1

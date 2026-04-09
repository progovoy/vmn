import os
import stat
import subprocess

import yaml

from helpers import (
    _add_buildmetadata_to_version,
    _goto,
    _init_app,
    _release_app,
    _run_vmn_init,
    _show,
    _stamp_app,
)


def test_basic_show(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    try:
        tmp = yaml.safe_load(captured.out)
        assert "dirty" not in tmp
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err = _show(app_layout.app_name)
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.file", "msg1", commit=False
    )

    err = _show(app_layout.app_name)
    assert err == 0

    captured = capfd.readouterr()
    assert "dirty" in captured.out

    err = _show(app_layout.app_name, ignore_dirty=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    try:
        tmp = yaml.safe_load(captured.out)
        assert "version_not_matched" in tmp["dirty"]
        assert "pending" in tmp["dirty"]
        assert len(tmp["dirty"]) == 2
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1", push=False)
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    try:
        tmp = yaml.safe_load(captured.out)
        assert "version_not_matched" in tmp["dirty"]
        assert "outgoing" in tmp["dirty"]
        assert len(tmp["dirty"]) == 2
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    try:
        tmp = yaml.safe_load(captured.out)
        assert "version_not_matched" in tmp["dirty"]
        assert len(tmp["dirty"]) == 1
    except Exception:
        assert False

    err = _goto(app_layout.app_name, version="0.0.1")
    assert err == 0

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _goto(app_layout.app_name)
    assert err == 0

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        url="https://whateverlink.com",
    )
    assert err == 0

    err = _add_buildmetadata_to_version(
        app_layout,
        "build.1-aef.1-its-okay",
        version="0.0.1",
        url="https://whateverlink.com",
    )
    assert err == 0

    captured = capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.2\n" == captured.out

    err = _show(app_layout.app_name, raw=True, version="0.0.1+build.1-aef.1-its-okay")
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.1+build.1-aef.1-its-okay\n" == captured.out

    err = _show(
        app_layout.app_name, display_type=True, version="0.0.1+build.1-aef.1-its-okay"
    )
    assert err == 0
    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["type"] == "metadata"
    assert tmp["out"] == "0.0.1+build.1-aef.1-its-okay"

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert f'0.0.2+{tmp["changesets"]["."]["hash"]}'.startswith(tmp["unique_id"])

    err = _show(app_layout.app_name, unique=True)
    assert err == 0
    captured = capfd.readouterr()
    assert f'0.0.2+{tmp["changesets"]["."]["hash"]}'.startswith(captured.out[:-1])

    err = _show(app_layout.app_name, display_type=True)
    assert err == 0
    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["type"] == "release"
    assert tmp["out"] == "0.0.2"


def test_show_from_file(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    capfd.readouterr()

    err = _show(app_layout.app_name, verbose=True, from_file=True)
    assert err == 1
    captured = capfd.readouterr()
    assert (
        f"[ERROR] Version information was not found "
        f"for {app_layout.app_name}.\n" in captured.err
    )

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    show_res = yaml.safe_load(captured.out)

    err = _show(app_layout.app_name, verbose=True, from_file=True)
    assert err == 0
    captured = capfd.readouterr()
    show_file_res_empty_ver = yaml.safe_load(captured.out)

    err = _show(app_layout.app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    captured = capfd.readouterr()
    show_file_res = yaml.safe_load(captured.out)

    assert show_file_res_empty_ver == show_file_res

    show_res.pop("versions")

    assert show_res == show_file_res

    app_name = "root_app/app1"
    _, _, params = _init_app(app_name)
    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    err, ver_info, params = _stamp_app(app_name, "patch")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"

    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 1

    capfd.readouterr()
    err = _show(app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    show_res = yaml.safe_load(captured.out)

    err = _show(app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    captured = capfd.readouterr()
    show_file_res = yaml.safe_load(captured.out)

    show_res.pop("versions")

    assert show_res == show_file_res

    capfd.readouterr()
    # TODO: Improve stdout in such a case
    err = _show(app_name, verbose=True, root=True)
    captured = capfd.readouterr()
    assert err == 0

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    captured = capfd.readouterr()
    show_root_res = yaml.safe_load(captured.out)

    err = _show("root_app", version="1", from_file=True, verbose=True, root=True)
    assert err == 0

    captured = capfd.readouterr()
    show_file_res = yaml.safe_load(captured.out)

    assert show_root_res == show_file_res

    err = _show(app_name)
    assert err == 0
    captured = capfd.readouterr()
    show_minimal_res = yaml.safe_load(captured.out)

    def rmtree(top):
        for root, dirs, files in os.walk(top, topdown=False):
            for name in files:
                filename = os.path.join(root, name)
                os.chmod(filename, stat.S_IWUSR)
                os.remove(filename)
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(top)

    rmtree(os.path.join(app_layout.repo_path, ".git"))

    err = _show("root_app", version="1", from_file=True, verbose=True, root=True)
    captured = capfd.readouterr()
    assert err == 0

    show_file_res = yaml.safe_load(captured.out)
    assert show_file_res == show_root_res

    err = _show(app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    captured = capfd.readouterr()
    show_file_res = yaml.safe_load(captured.out)
    assert show_file_res == show_res

    err = _show(app_name, version="0.0.1", from_file=True)
    assert err == 0
    captured = capfd.readouterr()
    show_file = yaml.safe_load(captured.out)

    assert show_minimal_res == show_file

    err = _show(app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    captured = capfd.readouterr()
    show_file_res = yaml.safe_load(captured.out)

    err = _show(app_name, version="0.0.1", from_file=True, unique=True)
    assert err == 0
    captured = capfd.readouterr()
    assert f'0.0.1+{show_file_res["changesets"]["."]["hash"]}'.startswith(
        captured.out[:-1]
    )


def test_show_from_file_conf_changed(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    capfd.readouterr()

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0
    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _show(app_layout.app_name, from_file=True)
    assert err == 0
    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
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

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.2\n" == captured.out

    err = _show(app_layout.app_name, from_file=True, raw=True)
    assert err == 0
    captured = capfd.readouterr()
    assert "0.0.1\n" == captured.out

    err = _show(app_layout.app_name, from_file=True, raw=True, version="0.0.2")
    assert err == 1
    captured = capfd.readouterr()
    assert (
        f"[ERROR] Version information was not found for "
        f"{app_layout.app_name}.\n" in captured.err
    )


def test_basic_root_show(app_layout, capfd):
    _run_vmn_init()
    app_name = "root_app/app1"
    ret, ver_info, params = _init_app(app_name, "0.2.1")
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.2.1"

    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 0

    app_name = "root_app/app2"
    _init_app(app_name, "0.2.1")

    capfd.readouterr()
    err = _show("root_app", root=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "1\n" == captured.out

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert app_name == out_dict["latest_service"]
    assert len(out_dict["services"]) == 2
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.1"

    err, _, _ = _stamp_app(app_name)
    assert err == 1
    captured = capfd.readouterr()
    assert (
        "[ERROR] When not in release candidate mode, a release mode must be "
        "specified - use -r/--release-mode with one of major/minor/patch/hotfix\n"
        == captured.err
    )

    err, ver_info, _ = _stamp_app(app_name, release_mode="patch")
    assert err == 0
    captured = capfd.readouterr()
    assert "[INFO] 0.2.2\n" == captured.out
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.2.2"

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert app_name == out_dict["latest_service"]
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.2"

    app_layout.write_file_commit_and_push("test_repo_0", "abc.txt", "a", push=False)

    err = _show("root_app", root=True)
    assert err == 0

    captured = capfd.readouterr()
    out_dict = yaml.safe_load(captured.out)
    assert out_dict["out"] == 2
    assert out_dict["dirty"][0] == "outgoing"


def test_show_on_local_only_branch_1_commit_after(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    app_layout._app_backend.be.get_active_branch()
    other_branch = "topic/abc"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1", push=False)

    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.0" == res["out"]
    assert len(res["dirty"]) == 2
    assert "version_not_matched" in res["dirty"]
    assert "outgoing" in res["dirty"]


def test_show_on_local_only_branch_0_commits_after(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    app_layout._app_backend.be.get_active_branch()
    other_branch = "topic/abc"

    app_layout.checkout(other_branch, create_new=True)

    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.0" == res["out"]
    assert len(res["dirty"]) == 2
    assert "version_not_matched" in res["dirty"]
    assert "outgoing" in res["dirty"]


def test_show_no_log_in_stdout(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "dirty:\n- version_not_matched\nout: 0.0.1\n\n" == captured.out

    result = subprocess.run(
        [
            "grep",
            "-q",
            "Test logprint in show",
            os.path.join(app_layout.repo_path, ".vmn", "vmn.log"),
        ]
    )
    assert result.returncode == 0


def test_show_no_ff_rebase_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    other_branch = "topic"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1")
    _stamp_app(app_layout.app_name, "patch", prerelease="rc")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")
    _stamp_app(app_layout.app_name)
    _release_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.1" == res["out"]

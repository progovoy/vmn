import sys
import os
import yaml
import shutil

sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))

import vmn
import stamp_utils

vmn.LOGGER = stamp_utils.init_stamp_logger(True)


def _init_vmn_in_repo(expected_res=0):
    with vmn.VMNContextMAnagerManager(["init"]) as vmn_ctx:
        err = vmn.handle_init(vmn_ctx)
        assert err == expected_res


def _init_app(app_name, starting_version="0.0.0"):
    with vmn.VMNContextMAnagerManager(
        [
            "init-app",
            "-v",
            starting_version,
            app_name,
        ]
    ) as vmn_ctx:
        err = vmn.handle_init_app(vmn_ctx)
        assert err == 0
        # TODO: why validating this?
        assert len(vmn_ctx.vcs.actual_deps_state) == 1

        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        return ver_info, vmn_ctx.params


def _release_app(app_name, version):
    with vmn.VMNContextMAnagerManager(["release", "-v", version, app_name]) as vmn_ctx:
        err = vmn.handle_release(vmn_ctx)
        assert err == 0

        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        return ver_info, vmn_ctx.params


def _stamp_app(app_name, release_mode=None, prerelease=None):
    args_list = ["stamp"]
    if release_mode is not None:
        args_list.extend(["-r", release_mode])

    if prerelease is not None:
        args_list.extend(["--pr", prerelease])

    args_list.append(app_name)

    with vmn.VMNContextMAnagerManager(args_list) as vmn_ctx:
        err = vmn.handle_stamp(vmn_ctx)
        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        return err, ver_info, vmn_ctx.params


def _show(app_name, verbose=None, raw=None, root=False):
    args_list = ["show"]
    if verbose is not None:
        args_list.append("--verbose")
    if raw is not None:
        args_list.append("--raw")
    if root:
        args_list.append("--root")

    args_list.append(app_name)

    with vmn.VMNContextMAnagerManager(args_list) as vmn_ctx:
        err = vmn.handle_show(vmn_ctx)
        assert err == 0


def test_basic_stamp(app_layout):
    _init_vmn_in_repo()
    _init_vmn_in_repo(1)
    _init_app(app_layout.app_name)

    for i in range(2):
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    new_name = "{0}_{1}".format(app_layout.app_name, "2")
    _init_app(new_name, "1.0.0")

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.1"

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_basic_show(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    _show(app_layout.app_name, raw=True)

    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    _show(app_layout.app_name, verbose=True)

    out, err = capfd.readouterr()
    try:
        yaml.safe_load(out)
    except Exception:
        assert False


def test_multi_repo_dependency(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "deps": {
            "../": {
                "test_repo": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
        "extra_info": False,
    }
    for repo in (("repo1", "git"), ("repo2", "git")):
        be = app_layout.create_repo(repo_name=repo[0], repo_type=repo[1])

        conf["deps"]["../"].update(
            {
                repo[0]: {
                    "vcs_type": repo[1],
                    "remote": be.be.remote(),
                }
            }
        )

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_file_commit_and_push(
        "repo1",
        "f1.file",
        "msg1",
    )
    app_layout.write_file_commit_and_push(
        "repo1",
        "f1.file",
        "msg1",
        commit=False,
    )

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    out, err = capfd.readouterr()
    assert "[INFO] Pending changes in" in out
    assert "repo1" in out
    app_layout.revert_changes("repo1")

    app_layout.write_file_commit_and_push(
        "repo1",
        "f1.file",
        "msg1",
        push=False,
    )

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    out, err = capfd.readouterr()
    assert "[INFO] Outgoing changes in" in out
    assert "repo1" in out
    app_layout.write_file_commit_and_push(
        "repo1",
        "f1.file",
        "msg1",
    )

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"

    assert "." in ver_info["stamping"]["app"]["changesets"]
    assert os.path.join("..", "repo1") in ver_info["stamping"]["app"]["changesets"]
    assert os.path.join("..", "repo2") in ver_info["stamping"]["app"]["changesets"]

    app_layout.write_conf(params["app_conf_path"], **conf)
    with open(params["app_conf_path"], "r") as f:
        data = yaml.safe_load(f)
        assert "../" in data["conf"]["deps"]
        assert "test_repo" in data["conf"]["deps"]["../"]
        assert "repo1" in data["conf"]["deps"]["../"]
        assert "repo2" in data["conf"]["deps"]["../"]


def test_goto_deleted_repos(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "deps": {
            "../": {
                "test_repo": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
        "extra_info": False,
    }
    for repo in (("repo1", "git"), ("repo2", "git")):
        be = app_layout.create_repo(repo_name=repo[0], repo_type=repo[1])

        conf["deps"]["../"].update(
            {
                repo[0]: {
                    "vcs_type": repo[1],
                    "remote": be.be.remote(),
                }
            }
        )

        be.__del__()

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dir_path = app_layout._repos["repo2"]["path"]
    # deleting repo_b
    shutil.rmtree(dir_path)

    with vmn.VMNContextMAnagerManager(
        ["goto", "-v", "0.0.2", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0


def test_basic_root_stamp(app_layout):
    _init_vmn_in_repo()

    app_name = "root_app/app1"
    _init_app(app_name)

    err, ver_info, params = _stamp_app(app_name, "patch")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"

    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 1

    app_name = "root_app/app2"
    _init_app(app_name)
    err, ver_info, params = _stamp_app(app_name, "minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 3


def test_starting_version(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"


def test_rc_stamping(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
        prerelease="rc",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        prerelease="rc",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        prerelease="beta",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta1"
    assert data["prerelease"] == "beta"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta2"
    assert data["prerelease"] == "beta"

    ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta2")

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    for item in ["2.0.0", "3.0.0"]:
        app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(
            app_layout.app_name,
            release_mode="major",
            prerelease="rc",
        )
        assert err == 0

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"{item}-rc1"
        assert data["prerelease"] == "rc"

        ver_info, _ = _release_app(app_layout.app_name, f"{item}-rc1")

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == item
        assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.1.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
        prerelease="rc",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.2.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
        prerelease="rc",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc1"
    assert data["prerelease"] == "rc"

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
        prerelease="release",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.4.0"
    assert data["prerelease"] == "release"
    assert not data["prerelease_count"]


def test_rc_goto(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    try:
        err, ver_info, _ = _stamp_app(
            app_layout.app_name,
            release_mode="minor",
            prerelease="rc_aaa",
        )
        assert err == 0
    except AssertionError:
        pass

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        release_mode="minor",
        prerelease="rcaaa",
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rcaaa1"

    with vmn.VMNContextMAnagerManager(
        ["goto", "-v", "1.3.0-rcaaa1", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0


def test_version_template():
    formated_version = (
        stamp_utils.VersionControlBackend.get_utemplate_formatted_version(
            "2.0.9",
            vmn.IVersionsStamper.parse_template("[{major}][-{prerelease}]"),
            True,
        )
    )

    assert formated_version == "2"

    formated_version = (
        stamp_utils.VersionControlBackend.get_utemplate_formatted_version(
            "2.0.9.0", vmn.IVersionsStamper.parse_template("[{major}][-{hotfix}]"), True
        )
    )

    assert formated_version == "2"

    formated_version = (
        stamp_utils.VersionControlBackend.get_utemplate_formatted_version(
            "2.0.9.0",
            vmn.IVersionsStamper.parse_template("[{major}][-{hotfix}]"),
            False,
        )
    )

    assert formated_version == "2-0"


def test_basic_goto(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"

    c1 = app_layout._app_backend.be.changeset()
    with vmn.VMNContextMAnagerManager(
        ["goto", "-v", "0.0.2", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 1
    with vmn.VMNContextMAnagerManager(
        ["goto", "-v", "1.3.0", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    out, err = capfd.readouterr()
    assert "[INFO] 1.3.0\n" == out

    c2 = app_layout._app_backend.be.changeset()
    assert c1 != c2
    with vmn.VMNContextMAnagerManager(
        ["goto", "-v", "1.3.1", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    with vmn.VMNContextMAnagerManager(["goto", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4


def test_stamp_on_branch_merge_squash(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    app_layout._app_backend.be.checkout(("-b", "new_branch"))
    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    app_layout._app_backend._origin.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout._app_backend._origin.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout.write_file_commit_and_push("test_repo", "f3.file", "msg3")
    app_layout._app_backend._origin.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout._app_backend.be.checkout("master")
    app_layout.merge(from_rev="new_branch", to_rev="master", squash=True)
    app_layout._app_backend._origin.pull(rebase=True)

    app_layout._app_backend.be.push()

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]

    assert data["_version"] == "1.3.3"


def test_get_version(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    app_layout._app_backend.be.checkout(("-b", "new_branch"))
    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    app_layout._app_backend._origin.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout._app_backend.be.checkout("master")
    app_layout.merge(from_rev="new_branch", to_rev="master", squash=True)
    app_layout._app_backend._origin.pull(rebase=True)
    app_layout._app_backend.be.push()
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"


def test_get_version_number_from_file(app_layout):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name, "0.2.1")

    assert vmn.VersionControlStamper.get_version_number_from_file(
        params["version_file_path"]
    ) == ("0.2.1", "release", {})


def test_read_version_from_file(app_layout):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    assert vmn.VersionControlStamper.get_version_number_from_file(file_path) == (
        "0.2.1",
        "release",
        {},
    )

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    app_layout._app_backend._origin.pull(rebase=True)
    with open(file_path, "r") as fid:
        ver_dict = yaml.load(fid)

    assert "0.2.1" == ver_dict["version_to_stamp_from"]


def test_manual_file_adjustment(app_layout):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    app_layout.remove_app_version_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": "0.2.3",
        "prerelease": "release",
        "prerelease_count": {},
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo",
        ".vmn/test_app/{}".format(vmn.VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "0.2.4" == _version


def test_basic_root_show(app_layout, capfd):
    _init_vmn_in_repo()
    app_name = "root_app/app1"
    ver_info, params = _init_app(app_name, "0.2.1")
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.2.1"

    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 0

    app_name = "root_app/app2"
    _init_app(app_name, "0.2.1")

    capfd.readouterr()
    _show("root_app", root=True)
    out, err = capfd.readouterr()
    assert "1\n" == out

    _show("root_app", verbose=True, root=True)
    out, err = capfd.readouterr()
    out_dict = yaml.safe_load(out)
    assert app_name == out_dict["latest_service"]
    assert len(out_dict["services"]) == 2
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.1"

    try:
        err, _, _ = _stamp_app(app_name)
        assert err == 0
    except AssertionError:
        pass

    err, ver_info, _ = _stamp_app(app_name, release_mode="patch")
    assert err == 0
    out, err = capfd.readouterr()
    assert "[INFO] 0.2.2\n" == out
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.2.2"

    _show("root_app", verbose=True, root=True)
    out, err = capfd.readouterr()
    out_dict = yaml.safe_load(out)
    assert app_name == out_dict["latest_service"]
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.2"


def test_backward_compatability_with_previous_vmn(app_layout, capfd):
    app_layout.stamp_with_previous_vmn()
    out, err = capfd.readouterr()
    err, ver_info, _ = _stamp_app("app1", "major")
    assert err == 0
    out, err = capfd.readouterr()
    assert "[INFO] 0.0.3\n" == out

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app("app1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.4"

    with vmn.VMNContextMAnagerManager(["goto", "-v", "0.0.2", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnagerManager(["goto", "-v", "0.0.3", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnagerManager(["goto", "-v", "0.0.4", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnagerManager(["goto", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

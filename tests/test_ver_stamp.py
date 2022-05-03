import copy
import sys
import os
import yaml
import shutil
import toml
import json
import stat
import pytest

sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))

import vmn
import stamp_utils

vmn.LOGGER = stamp_utils.init_stamp_logger(True)


def _init_vmn_in_repo(expected_res=0):
    with vmn.VMNContextMAnager(["init"]) as vmn_ctx:
        err = vmn.handle_init(vmn_ctx)
        assert err == expected_res


def _init_app(app_name, starting_version="0.0.0"):
    with vmn.VMNContextMAnager(
        ["init-app", "-v", starting_version, app_name]
    ) as vmn_ctx:
        err = vmn.handle_init_app(vmn_ctx)
        assert err == 0
        # TODO: why validating this?
        assert len(vmn_ctx.vcs.actual_deps_state) == 1

        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        try:
            # Python3.9 only
            merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
        except:
            merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

        return ver_info, merged_dict


def _release_app(app_name, version):
    with vmn.VMNContextMAnager(["release", "-v", version, app_name]) as vmn_ctx:
        err = vmn.handle_release(vmn_ctx)
        assert err == 0

        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        try:
            # Python3.9 only
            merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
        except:
            merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

        return ver_info, merged_dict


def _stamp_app(app_name, release_mode=None, prerelease=None):
    args_list = ["stamp"]
    if release_mode is not None:
        args_list.extend(["-r", release_mode])

    if prerelease is not None:
        args_list.extend(["--pr", prerelease])

    args_list.append(app_name)

    with vmn.VMNContextMAnager(args_list) as vmn_ctx:
        err = vmn.handle_stamp(vmn_ctx)
        ver_info = vmn_ctx.vcs.backend.get_vmn_version_info(app_name)

        try:
            # Python3.9 only
            merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
        except:
            merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

        return err, ver_info, merged_dict


def _show(
    app_name,
    version=None,
    verbose=None,
    raw=None,
    root=False,
    from_file=False,
    ignore_dirty=False,
):
    args_list = ["show"]
    if verbose is not None:
        args_list.append("--verbose")
    if version is not None:
        args_list.extend(["--version", f"{version}"])
    if raw is not None:
        args_list.append("--raw")
    if root:
        args_list.append("--root")
    if from_file:
        args_list.append("--from-file")
    if ignore_dirty:
        args_list.append("--ignore-dirty")

    args_list.append(app_name)

    with vmn.VMNContextMAnager(args_list) as vmn_ctx:
        err = vmn.handle_show(vmn_ctx)
        return err


def _gen(app_name, template, output, verify_version=False, version=None):
    args_list = ["--debug"]
    args_list.extend(["gen"])
    args_list.extend(["--template", template])
    args_list.extend(["--output", output])

    if version is not None:
        args_list.extend(["--version", f"{version}"])

    if verify_version:
        args_list.extend(["--verify-version"])

    args_list.append(app_name)

    with vmn.VMNContextMAnager(args_list) as vmn_ctx:
        err = vmn.handle_gen(vmn_ctx)
        return err


def test_basic_stamp(app_layout):
    _init_vmn_in_repo()
    _init_vmn_in_repo(1)
    _init_app(app_layout.app_name)

    for i in range(2):
        err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    new_name = f"{app_layout.app_name}_2"
    _init_app(new_name, "1.0.0")

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.1"

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo", "a/b/c/f1.file", "msg1")
    os.environ["VMN_WORKING_DIR"] = f"{app_layout.repo_path}/a/b/c/"

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.2"

    for i in range(2):
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.2"

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.2"

    _init_app("myapp")


@pytest.mark.parametrize("hook_name", ["pre-push", "post-commit", "pre-commit"])
def test_git_hooks(app_layout, capfd, hook_name):
    _init_vmn_in_repo()
    _init_vmn_in_repo(1)
    _, params = _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo", "f1.txt", "connnntenctt")

    # More post-checkout, post-commit, post-merge, post-rewrite, pre-commit, pre-push
    app_layout.write_file_commit_and_push(
        "test_repo",
        f".git/hooks/{hook_name}",
        "#/bin/bash\nexit 1",
        add_exec=True,
        commit=False,
    )

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1 (dirty): {'modified'}\n" == out

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 1

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1 (dirty): {'modified'}\n" == out

    app_layout.remove_file(
        os.path.join(params["root_path"], f".git/hooks/{hook_name}"), from_git=False
    )

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.2\n" == out


def test_jinja2_gen(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    app_layout.write_file_commit_and_push("test_repo", "f1.txt", "content")

    jinja2_content = (
        "VERSION: {{version}} \n"
        "NAME: {{name}} \n"
        "BRANCH: {{stamped_on_branch}} \n"
        "RELEASE_MODE: {{release_mode}} \n"
        "{% for k,v in changesets.items() %} \n"
        "    <h2>REPO: {{k}}\n"
        "    <h2>HASH: {{v.hash}}</h2> \n"
        "    <h2>REMOTE: {{v.remote}}</h2> \n"
        "    <h2>VCS_TYPE: {{v.vcs_type}}</h2> \n"
        "{% endfor %}\n"
    )
    app_layout.write_file_commit_and_push(
        "test_repo", "f1.jinja2", jinja2_content, commit=False, push=False
    )

    tpath = os.path.join(app_layout._repos["test_repo"]["path"], "f1.jinja2")
    opath = os.path.join(app_layout._repos["test_repo"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 1

    out, err = capfd.readouterr()

    assert out.startswith("[ERROR] The repository is in dirty state. Refusing to gen")

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True, version="0.0.1")
    assert err == 1

    out, err = capfd.readouterr()

    assert out.startswith("[ERROR] The repository is not exactly at version: 0.0.1")

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.1", "test_app"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 0

    with vmn.VMNContextMAnager(["goto", "test_app"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 1

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    new_name = f"{app_layout.app_name}2/s1"
    _init_app(new_name)

    err, _, _ = _stamp_app(new_name, "patch")
    assert err == 0

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0


def test_basic_show(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    out, err = capfd.readouterr()
    try:
        tmp = yaml.safe_load(out)
        assert "dirty" not in tmp
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1", commit=False)

    err = _show(app_layout.app_name)
    assert err == 0

    out, err = capfd.readouterr()
    assert "dirty" in out

    err = _show(app_layout.app_name, ignore_dirty=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    out, err = capfd.readouterr()
    try:
        tmp = yaml.safe_load(out)
        assert "modified" in tmp["dirty"]
        assert "pending" in tmp["dirty"]
        assert len(tmp["dirty"]) == 2
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1", push=False)
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    out, err = capfd.readouterr()
    try:
        tmp = yaml.safe_load(out)
        assert "modified" in tmp["dirty"]
        assert "outgoing" in tmp["dirty"]
        assert len(tmp["dirty"]) == 2
    except Exception:
        assert False

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    out, err = capfd.readouterr()
    try:
        tmp = yaml.safe_load(out)
        assert "modified" in tmp["dirty"]
        assert len(tmp["dirty"]) == 1
    except Exception:
        assert False

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.1", "test_app"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1\n" == out


def test_show_from_file(app_layout, capfd):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name)
    capfd.readouterr()

    err = _show(app_layout.app_name, verbose=True, from_file=True)
    assert err == 1
    out, err = capfd.readouterr()
    assert (
        out == f"[INFO] Version information was not found for {app_layout.app_name}.\n"
    )

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_res = yaml.safe_load(out)

    err = _show(app_layout.app_name, verbose=True, from_file=True)
    assert err == 0
    out, err = capfd.readouterr()
    show_file_res_empty_ver = yaml.safe_load(out)

    err = _show(app_layout.app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_file_res = yaml.safe_load(out)

    assert show_file_res_empty_ver == show_file_res

    assert show_res == show_file_res

    app_name = "root_app/app1"
    _, params = _init_app(app_name)
    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    out, err = capfd.readouterr()
    show_res = yaml.safe_load(out)

    err = _show(app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_file_res = yaml.safe_load(out)

    assert show_res == show_file_res

    capfd.readouterr()
    # TODO: Improve stdout in such a case
    err = _show(app_name, verbose=True, root=True)
    assert err == 1
    out, err = capfd.readouterr()

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_root_res = yaml.safe_load(out)

    err = _show("root_app", version="1", from_file=True, verbose=True, root=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_file_res = yaml.safe_load(out)

    assert show_root_res == show_file_res

    err = _show(app_name)
    assert err == 0
    out, err = capfd.readouterr()
    show_minimal_res = yaml.safe_load(out)

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
    assert err == 0

    out, err = capfd.readouterr()
    show_file_res = yaml.safe_load(out)
    assert show_file_res == show_root_res

    err = _show(app_name, version="0.0.1", verbose=True, from_file=True)
    assert err == 0

    out, err = capfd.readouterr()
    show_file_res = yaml.safe_load(out)
    assert show_file_res == show_res

    err = _show(app_name, version="0.0.1", from_file=True)
    assert err == 0
    out, err = capfd.readouterr()
    show_file = yaml.safe_load(out)

    assert show_minimal_res == show_file


def test_show_from_file_conf_changed(app_layout, capfd):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name)
    capfd.readouterr()

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "create_verinfo_files": True,
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

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0
    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    err = _show(app_layout.app_name, from_file=True)
    assert err == 0
    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

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

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    out, err = capfd.readouterr()
    assert not err

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "0.0.2\n" == out

    err = _show(app_layout.app_name, from_file=True, raw=True)
    assert err == 0
    out, err = capfd.readouterr()
    assert "0.0.1\n" == out

    err = _show(app_layout.app_name, from_file=True, raw=True, version="0.0.2")
    assert err == 1
    out, err = capfd.readouterr()
    assert (
        f"[INFO] Version information was not found for {app_layout.app_name}.\n" == out
    )


def test_multi_repo_dependency(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "deps": {
            "../": {
                "test_repo": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        }
    }
    for repo in (("repo1", "git"), ("repo2", "git")):
        be = app_layout.create_repo(repo_name=repo[0], repo_type=repo[1])

        conf["deps"]["../"].update(
            {repo[0]: {"vcs_type": repo[1], "remote": be.be.remote()}}
        )

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1", commit=False)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    out, err = capfd.readouterr()
    assert "[ERROR] \nPending changes in" in out
    assert "repo1" in out
    app_layout.revert_changes("repo1")

    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1", push=False)

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1
    out, err = capfd.readouterr()
    assert "[ERROR] \nOutgoing changes in" in out
    assert "repo1" in out
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")

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

    conf["deps"]["../"]["repo3"] = copy.deepcopy(conf["deps"]["../"]["repo2"])

    app_layout.write_conf(params["app_conf_path"], **conf)
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1


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
            {repo[0]: {"vcs_type": repo[1], "remote": be.be.remote()}}
        )

        be.__del__()

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dir_path = app_layout._repos["repo2"]["path"]
    # deleting repo_b
    shutil.rmtree(dir_path)

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.2", app_layout.app_name]) as vmn_ctx:
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

    app_name = "root_app/app3"
    _init_app(app_name)
    err, ver_info, params = _stamp_app(app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 5

    app_name = "root_app/app1"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.1"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 1

    app_name = "root_app/app2"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 3

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "blabla")

    app_name = "root_app/app1"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 6
    assert "root_app/app1" in data["services"]
    assert "root_app/app2" in data["services"]

    app_name = "root_app/app2"
    err, ver_info, params = _stamp_app(app_name, "major")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.0"
    data = ver_info["stamping"]["root_app"]
    assert data["version"] == 7

    assert data["services"]["root_app/app1"] == "1.0.0"
    assert data["services"]["root_app/app2"] == "1.0.0"
    assert data["services"]["root_app/app3"] == "0.0.1"


def test_starting_version(app_layout):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"


def test_rc_stamping(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="beta")
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

    tags_before = app_layout._app_backend.be.tags()
    for t in tags_before:
        app_layout._app_backend.be._be.delete_tag(t)

    app_layout._app_backend.be._be.git.fetch("--tags")
    tags_after = app_layout._app_backend.be.tags()

    assert tags_before == tags_after

    for item in ["2.0.0", "3.0.0"]:
        app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="major", prerelease="rc"
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

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.1.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.2.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
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

    for item in ["3.4.0", "3.5.0"]:
        app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="minor", prerelease="release"
        )
        assert err == 0

        data = ver_info["stamping"]["app"]
        assert data["_version"] == item
        assert data["prerelease"] == "release"
        assert not data["prerelease_count"]

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.6.0-rc1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.6.0-rc2"
    assert data["prerelease"] == "rc"

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    out, err = capfd.readouterr()
    assert "3.6.0-rc2\n" == out

    ver_info, _ = _release_app(app_layout.app_name, f"3.6.0-rc1")

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    out, err = capfd.readouterr()
    assert "3.6.0\n" == out

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.7.0-rc1"
    assert data["prerelease"] == "rc"


def test_rc_goto(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    try:
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="minor", prerelease="rc_aaa"
        )
        assert err == 0
    except AssertionError:
        pass

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rcaaa"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rcaaa1"

    with vmn.VMNContextMAnager(
        ["goto", "-v", "1.3.0-rcaaa1", app_layout.app_name]
    ) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0


def test_goto_print(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")

    app_layout.write_file_commit_and_push("test_repo", "my.js", "some text")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="major")

    capfd.readouterr()

    with vmn.VMNContextMAnager(["goto", "-v", "1.3.0", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

        sout, serr = capfd.readouterr()
        assert f"[INFO] You are at version 1.3.0 of {app_layout.app_name}\n" == sout

    with vmn.VMNContextMAnager(["goto", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

        sout, serr = capfd.readouterr()
        assert (
            f"[INFO] You are at the tip of the branch of version 2.0.0 for {app_layout.app_name}\n"
            == sout
        )


def test_version_template():
    formated_version = stamp_utils.VMNBackend.get_utemplate_formatted_version(
        "2.0.9", vmn.IVersionsStamper.parse_template("[{major}][-{prerelease}]"), True
    )

    assert formated_version == "2"

    formated_version = stamp_utils.VMNBackend.get_utemplate_formatted_version(
        "2.0.9.0", vmn.IVersionsStamper.parse_template("[{major}][-{hotfix}]"), True
    )

    assert formated_version == "2"

    formated_version = stamp_utils.VMNBackend.get_utemplate_formatted_version(
        "2.0.9.0", vmn.IVersionsStamper.parse_template("[{major}][-{hotfix}]"), False
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
    with vmn.VMNContextMAnager(["goto", "-v", "0.0.2", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 1
    with vmn.VMNContextMAnager(["goto", "-v", "1.3.0", app_layout.app_name]) as vmn_ctx:
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
    with vmn.VMNContextMAnager(["goto", "-v", "1.3.1", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    with vmn.VMNContextMAnager(["goto", app_layout.app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4

    root_app_name = "some_root_app/service1"
    _init_app(root_app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc1 = app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc2 = app_layout._app_backend.be.changeset()

    assert rc1 != rc2

    with vmn.VMNContextMAnager(["goto", "-v", "1.3.0", root_app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    with vmn.VMNContextMAnager(["goto", root_app_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.5.0"

    rc3 = app_layout._app_backend.be.changeset()

    root_name = root_app_name.split("/")[0]

    with vmn.VMNContextMAnager(["goto", "--root", "-v", "1", root_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    with vmn.VMNContextMAnager(["goto", "--root", root_name]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    assert rc3 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0


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
        ver_dict = yaml.load(fid, Loader=yaml.FullLoader)

    assert "0.2.1" == ver_dict["version_to_stamp_from"]


def test_manual_file_adjustment(app_layout):
    _init_vmn_in_repo()
    _, params = _init_app(app_layout.app_name, "0.2.1")

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
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
    err = _show("root_app", root=True)
    assert err == 0

    out, err = capfd.readouterr()
    assert "1\n" == out

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    out, err = capfd.readouterr()
    out_dict = yaml.safe_load(out)
    assert app_name == out_dict["latest_service"]
    assert len(out_dict["services"]) == 2
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.1"

    err, _, _ = _stamp_app(app_name)
    assert err == 1
    out, err = capfd.readouterr()
    assert (
        "[ERROR] When not in release candidate mode, a release mode must be "
        "specified - use -r/--release-mode with one of major/minor/patch/hotfix\n"
        == out
    )

    err, ver_info, _ = _stamp_app(app_name, release_mode="patch")
    assert err == 0
    out, err = capfd.readouterr()
    assert "[INFO] 0.2.2\n" == out
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.2.2"

    err = _show("root_app", verbose=True, root=True)
    assert err == 0

    out, err = capfd.readouterr()
    out_dict = yaml.safe_load(out)
    assert app_name == out_dict["latest_service"]
    assert app_name in out_dict["services"]
    assert out_dict["services"][app_name] == "0.2.2"


def test_version_backends_cargo(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo",
        "Cargo.toml",
        toml.dumps({"package": {"name": "test_app", "version": "some ignored string"}}),
    )

    conf = {
        "version_backends": {"cargo": {"path": "Cargo.toml"}},
        "deps": {
            "../": {
                "test_repo": {
                    "vcs_type": app_layout.be_type,
                    "remote": app_layout._app_backend.be.remote(),
                }
            }
        },
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["cargo"]["path"]
    )

    with open(full_path, "r") as f:
        data = toml.load(f)
        assert data["package"]["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_conf(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo", "f1.txt", "text")

    conf = {
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

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {"deps": {}, "extra_info": False}

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_version_backends_npm(app_layout, capfd):
    _init_vmn_in_repo()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo",
        "package.json",
        json.dumps({"name": "test_app", "version": "some ignored string"}),
    )

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "version_backends": {"npm": {"path": "package.json"}},
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

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["npm"]["path"]
    )

    with open(full_path, "r") as f:
        data = json.load(f)
        assert data["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


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

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.2", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.3", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnager(["goto", "-v", "0.0.4", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    with vmn.VMNContextMAnager(["goto", "app1"]) as vmn_ctx:
        err = vmn.handle_goto(vmn_ctx)
        assert err == 0

    err, ver_info, _ = _stamp_app("root_app/service1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_remotes(app_layout):
    _init_vmn_in_repo()
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

        app_layout.write_file_commit_and_push("test_repo", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == f"0.0.{c}"
        c += 1

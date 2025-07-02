import copy
import json
import os
import shutil
import stat
import subprocess
import sys

import pytest
import toml
import yaml

sys.path.append("{0}/../version_stamp".format(os.path.dirname(__file__)))

import vmn
import stamp_utils


def _run_vmn_init():
    stamp_utils.VMN_LOGGER = None
    ret = vmn.vmn_run(["init"])[0]
    return ret


def _init_app(app_name, starting_version="0.0.0"):
    cmd = ["init-app", "-v", starting_version, app_name]
    stamp_utils.VMN_LOGGER = None
    ret, vmn_ctx = vmn.vmn_run(cmd)

    tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
        app_name, type=stamp_utils.RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE
    )

    vmn_ctx.vcs.enhance_ver_info(ver_infos)

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]

    try:
        # Python3.9 only
        merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
    except:
        merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

    return ret, ver_info, merged_dict


def _release_app(app_name, version=None):
    cmd = ["release", app_name]
    if version:
        cmd.extend(["-v", version])

    stamp_utils.VMN_LOGGER = None
    ret, vmn_ctx = vmn.vmn_run(cmd)

    vmn_ctx.vcs.initialize_backend_attrs()

    if version is None:
        tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
            app_name, type=stamp_utils.RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE
        )
    else:
        tag_name, ver_infos = vmn_ctx.vcs.get_version_info_from_verstr(
            stamp_utils.VMNBackend.get_base_vmn_version(
                version, hide_zero_hotfix=vmn_ctx.vcs.hide_zero_hotfix
            )
        )

    vmn_ctx.vcs.enhance_ver_info(ver_infos)

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]

    try:
        # Python3.9 only
        merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
    except:
        merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

    return ret, ver_info, merged_dict


def _stamp_app(
    app_name,
    release_mode=None,
    optional_release_mode=None,
    prerelease=None,
    override_version=None,
):
    args_list = ["stamp"]
    if release_mode is not None:
        args_list.extend(["-r", release_mode])

    if optional_release_mode is not None:
        args_list.extend(["--orm", optional_release_mode])

    if prerelease is not None:
        args_list.extend(["--pr", prerelease])

    if override_version is not None:
        args_list.extend(["--ov", override_version])

    args_list.append(app_name)

    stamp_utils.VMN_LOGGER = None
    ret, vmn_ctx = vmn.vmn_run(args_list)

    tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
        app_name, type=stamp_utils.RELATIVE_TO_CURRENT_VCS_POSITION_TYPE
    )

    vmn_ctx.vcs.enhance_ver_info(ver_infos)

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]

    try:
        # Python3.9 only
        merged_dict = vmn_ctx.params | vmn_ctx.vcs.__dict__
    except:
        merged_dict = {**(vmn_ctx.params), **(vmn_ctx.vcs.__dict__)}

    return ret, ver_info, merged_dict


def _show(
    app_name,
    version=None,
    verbose=None,
    raw=None,
    root=False,
    from_file=False,
    ignore_dirty=False,
    unique=False,
    display_type=False,
    template=None,
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
    if unique:
        args_list.append("--unique")
    if display_type:
        args_list.append("--type")
    if template:
        args_list.extend(["-t", f"{template}"])

    args_list.append(app_name)

    stamp_utils.VMN_LOGGER = None
    ret = vmn.vmn_run(args_list)

    return ret[0]


def _gen(
    app_name, template, output, verify_version=False, version=None, custom_path=None
):
    args_list = ["--debug"]
    args_list.extend(["gen"])
    args_list.extend(["--template", template])
    args_list.extend(["--output", output])

    if version is not None:
        args_list.extend(["--version", f"{version}"])

    if verify_version:
        args_list.extend(["--verify-version"])

    if custom_path is not None:
        args_list.extend(["-c", f"{custom_path}"])

    args_list.append(app_name)

    stamp_utils.VMN_LOGGER = None
    ret = vmn.vmn_run(args_list)[0]

    return ret


def _goto(app_name, version=None, root=False):
    args_list = ["goto"]
    if version is not None:
        args_list.extend(["--version", f"{version}"])
    if root:
        args_list.append("--root")

    args_list.append(app_name)

    stamp_utils.VMN_LOGGER = None
    ret = vmn.vmn_run(args_list)[0]

    return ret


def _add_buildmetadata_to_version(
    app_layout, bm, version=None, file_path=None, url=None
):
    args_list = ["--debug"]
    args_list.extend(["add"])
    args_list.extend(["--bm", bm])
    app_name = app_layout.app_name

    if version is not None:
        args_list.extend(["--version", version])

    if file_path is not None:
        args_list.extend(
            [
                "--version-metadata-path",
                f"{os.path.join(app_layout.repo_path, file_path)}",
            ]
        )

    if url:
        args_list.extend(["--version-metadata-url", url])

    args_list.append(app_name)

    stamp_utils.VMN_LOGGER = None
    ret = vmn.vmn_run(args_list)[0]

    return ret


def _configure_2_deps(
    app_layout, params, specific_branch=None, specific_hash=None, specific_tag=None
):
    conf = {
        "deps": {
            "../": {
                "test_repo_0": {
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
        if specific_branch:
            cur_branch = app_layout._repos[repo[0]]["_be"].be.get_active_branch()
            app_layout.checkout("new_branch", repo_name=repo[0], create_new=True)
            app_layout.write_file_commit_and_push(repo[0], "f1.file", "msg1")
            app_layout.write_file_commit_and_push(repo[0], "f1.file", "msg1")
            app_layout.checkout(cur_branch, repo_name=repo[0])
            conf["deps"]["../"][repo[0]].update({"branch": specific_branch})

        be.__del__()

    app_layout.write_conf(params["app_conf_path"], **conf)

    return conf


def _configure_empty_conf(app_layout, params):
    conf = {"deps": {}, "extra_info": False}
    app_layout.write_conf(params["app_conf_path"], **conf)

    return conf


def test_vmn_init(app_layout, capfd):
    res = _run_vmn_init()
    assert res == 0
    captured = capfd.readouterr()

    assert (
        f"[INFO] Initialized vmn tracking on {app_layout.repo_path}\n" == captured.out
    )
    assert "" == captured.err

    res = _run_vmn_init()
    assert res == 1

    captured = capfd.readouterr()
    assert captured.err.startswith("[ERROR] vmn repo tracking is already initialized")
    assert "" == captured.out


def test_double_stamp_no_commit(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    for i in range(2):
        err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_app2_and_app1_not_advance(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    new_name = f"{app_layout.app_name}_2"
    _init_app(new_name, "1.0.0")

    for i in range(2):
        err, ver_info, _ = _stamp_app(new_name, "hotfix")
        assert err == 0
        assert ver_info["stamping"]["app"]["_version"] == "1.0.0.1"

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_stamp_multiple_apps(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    new_name = f"{app_layout.app_name}_2"
    _init_app(new_name, "1.0.0")

    _stamp_app(new_name, "hotfix")

    repo_name = app_layout.repo_path.split(os.path.sep)[-1]
    app_layout.write_file_commit_and_push(
        f"{repo_name}", os.path.join("a", "b", "c", "f1.file"), "msg1"
    )
    os.environ[
        "VMN_WORKING_DIR"
    ] = f"{os.path.join(app_layout.repo_path, 'a', 'b', 'c')}"

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
    res = _run_vmn_init()
    assert res == 0
    res = _run_vmn_init()
    assert res == 1
    _, _, params = _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "connnntenctt")

    # More post-checkout, post-commit, post-merge, post-rewrite, pre-commit, pre-push
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        f".git/hooks/{hook_name}",
        "#/bin/bash\nexit 1",
        add_exec=True,
        commit=False,
    )

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"
    assert "modified" in tmp["dirty"]

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 1

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["out"] == "0.0.1"
    assert "modified" in tmp["dirty"]

    app_layout.remove_file(
        os.path.join(params["root_path"], f".git/hooks/{hook_name}"), from_git=False
    )

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "0.0.2\n" == captured.out


def test_jinja2_gen(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = (
        "VERSION: {{version}}\n"
        "NAME: {{name}}\n"
        "BRANCH: {{stamped_on_branch}}\n"
        "RELEASE_MODE: {{release_mode}}\n"
        "{% for k,v in changesets.items() %}\n"
        "{{k}}:\n"
        "  hash: {{v.hash}}\n"
        "  remote: {{v.remote}}\n"
        "  vcs_type: {{v.vcs_type}}\n"
        "  state: {{v.state}}\n"
        "{% endfor %}\n"
    )
    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.jinja2", jinja2_content, commit=False
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    m_time = os.path.getmtime(opath)

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    m_time_after = os.path.getmtime(opath)

    assert m_time == m_time_after

    # read to clear stderr and out
    capfd.readouterr()

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 1

    captured = capfd.readouterr()

    assert (
        "[ERROR] The repository and maybe"
        " some of its dependencies are in dirty state.Dirty states"
        " found: {'modified'}" in captured.err
    )

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    capfd.readouterr()

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True, version="0.0.1")
    assert err == 1

    captured = capfd.readouterr()

    assert (
        "[ERROR] The repository is not exactly at "
        "version: 0.0.1. You can use `vmn goto` in order "
        "to jump to that version.\nRefusing to gen." in captured.err
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    err = _goto(app_layout.app_name, version="0.0.1")
    assert err == 0

    err = _gen(app_layout.app_name, tpath, opath, verify_version=True)
    assert err == 0

    err = _goto(app_layout.app_name)
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

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg1")
    app_layout.write_file_commit_and_push("repo1", "f1.file", "msg2", commit=False)
    app_layout.write_file_commit_and_push("repo2", "f1.file", "msg1", push=False)

    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.3"
        assert data["RELEASE_MODE"] == "patch"
        assert "dirty_deps" in data["."]["state"]
        assert "modified" in data["."]["state"]
        assert "pending" in data[os.path.join("..", "repo1")]["state"]
        assert "outgoing" in data[os.path.join("..", "repo2")]["state"]


def test_jinja2_gen_custom(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = "VERSION: {{version}}\n" "Custom: {{k1}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    custom_path = os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath, custom_path=custom_path)
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.1"
        assert data["Custom"] == 5


def test_version_backends_generic_jinja(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    jinja2_content = "VERSION: {{version}}\n" "Custom: {{k1}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_jinja = {
        "generic_jinja": [
            {
                "input_file_path": "f1.jinja2",
                "output_file_path": "jinja_out.txt",
                "custom_keys_path": "custom.yml",
            },
        ]
    }

    conf = {"version_backends": generic_jinja}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["VERSION"] == "0.0.2"
        assert data["Custom"] == 5


def test_version_backends_generic_selectors(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in2.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                        "custom_keys_path": "custom.yml",
                    },
                    {
                        "input_file_path": "in2.txt",
                        "output_file_path": "in2.txt",
                    },
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){stamp_utils._VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                    {"regex_selector": "(Custom: )([0-9]+)", "regex_sub": r"\1{{k1}}"},
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")
    opath2 = os.path.join(app_layout._repos["test_repo_0"]["path"], "in2.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] == 5

    with open(opath2, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] is None


def test_version_backends_generic_selectors_no_custom_keys(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){stamp_utils._VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2-x"
        assert data["Custom"] == 3


def test_version_backends_generic_selectors_regex_vars(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0", "in.txt", yaml.safe_dump({"version": "9.3.2-rc.4", "Custom": 3})
    )

    custom_keys_content = "k1: 5\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                        "custom_keys_path": "custom.yml",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": "(version: )({{VMN_VERSION_REGEX}})",
                        "regex_sub": r"\1{{version}}",
                    },
                    {"regex_selector": "(Custom: )([0-9]+)", "regex_sub": r"\1{{k1}}"},
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2"
        assert data["Custom"] == 5


def test_generic_selectors_multiple_apps_same_file_same_diff(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    second_app = f"{app_layout.app_name}_2"
    _, _, params2 = _init_app(second_app)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){stamp_utils._VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_conf(params2["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.2-x"
        assert data["Custom"] == 3


def test_generic_selectors_multiple_apps_same_file_diff(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)
    second_app = f"{app_layout.app_name}_2"
    _, _, params2 = _init_app(second_app)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "major")
    assert ver_info2["stamping"]["app"]["_version"] == "1.0.0"
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        yaml.safe_dump({"version": "9.3.2-rc.4-x", "Custom": 3}),
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){stamp_utils._VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)
    app_layout.write_conf(params2["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"
    assert err == 0

    err, ver_info2, _ = _stamp_app(second_app, "patch")
    assert ver_info2["stamping"]["app"]["_version"] == "1.0.1"
    assert err == 0

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.3"
    assert err == 0

    with open(opath, "r") as f:
        data = yaml.safe_load(f)
        assert data["version"] == "0.0.3-x"
        assert data["Custom"] == 3


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
        assert "modified" in tmp["dirty"]
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
        assert "modified" in tmp["dirty"]
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
        assert "modified" in tmp["dirty"]
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
    assert captured.out == "dirty:\n- modified\nout: 0.0.3\n\n"

    err = _goto(app_layout.app_name)
    assert err == 0


def test_goto_deleted_repos(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    _configure_2_deps(app_layout, params)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    dir_path = app_layout._repos["repo2"]["path"]
    # deleting repo_b
    shutil.rmtree(dir_path)

    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 0


def test_basic_root_stamp(app_layout):
    _run_vmn_init()

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

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "blabla")

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


def test_starting_version(app_layout, capfd):
    _run_vmn_init()
    capfd.readouterr()
    _init_app(app_layout.app_name, "1.2.3")
    captured = capfd.readouterr()

    path = f"{os.path.join(app_layout.repo_path, '.vmn', app_layout.app_name)}"
    assert f"[INFO] Initialized app tracking on {path}\n" == captured.out

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"


def test_rc_stamping(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="beta")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.1"
    assert data["prerelease"] == "beta"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.2"
    assert data["prerelease"] == "beta"

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.2")
    capfd.readouterr()

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0")

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    tags_before = app_layout.get_all_tags()
    for t in tags_before:
        app_layout._app_backend.be._be.delete_tag(t)

    app_layout._app_backend.be._be.git.fetch("--tags")
    tags_after = app_layout.get_all_tags()

    assert tags_before == tags_after

    for item in ["2.0.0", "3.0.0"]:
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="major", prerelease="rc"
        )
        assert err == 0

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"{item}-rc.1"
        assert data["prerelease"] == "rc"

        _, ver_info, _ = _release_app(app_layout.app_name, f"{item}-rc.1")

        assert "vmn_info" in ver_info
        data = ver_info["stamping"]["app"]
        assert data["_version"] == item
        assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.1.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.2.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc.1"
    assert data["prerelease"] == "rc"

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.3.0-rc.2"
    assert data["prerelease"] == "rc"

    for item in ["3.4.0", "3.5.0"]:
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

        err, ver_info, _ = _stamp_app(
            app_layout.app_name, release_mode="minor", prerelease="release"
        )
        assert err == 0

        data = ver_info["stamping"]["app"]
        assert data["_version"] == item
        assert data["prerelease"] == "release"
        assert not data["prerelease_count"]

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.6.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.6.0-rc.2"
    assert data["prerelease"] == "rc"

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    captured = capfd.readouterr()
    assert "3.6.0-rc.2\n" == captured.out

    err = _show(app_layout.app_name, display_type=True)
    assert err == 0
    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert tmp["type"] == "rc"
    assert tmp["out"] == "3.6.0-rc.2"

    _, ver_info, _ = _release_app(app_layout.app_name, "3.6.0-rc.1")

    capfd.readouterr()
    err = _show(app_layout.app_name)
    assert err == 0

    captured = capfd.readouterr()
    assert "3.6.0-rc.2\n" == captured.out

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.7.0-rc.1"
    assert data["prerelease"] == "rc"

    _, ver_info, _ = _release_app(app_layout.app_name, "3.7.0-rc.1")

    assert "vmn_info" in ver_info
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "3.7.0"
    assert data["prerelease"] == "release"

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

    captured = capfd.readouterr()
    assert (
        "[INFO] Found existing version 3.7.0 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )

    for i in range(2):
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

    _, ver_info, _ = _release_app(app_layout.app_name, "3.8.0-rc.2")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 0

    captured = capfd.readouterr()
    assert (
        "[INFO] Found existing version 3.8.0-rc.3 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    assert err == 1

    captured = capfd.readouterr()
    assert captured.err.startswith("[ERROR] The version 3.8.0 was already ")


def test_rc_goto(app_layout, capfd):
    _run_vmn_init()
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
    assert data["_version"] == "1.3.0-rcaaa.1"

    err = _goto(app_layout.app_name, version="1.3.0-rcaaa.1")
    assert err == 0


def test_goto_print(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")

    app_layout.write_file_commit_and_push("test_repo_0", "my.js", "some text")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="major")

    capfd.readouterr()

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    sout, serr = capfd.readouterr()
    assert f"[INFO] You are at version 1.3.0 of {app_layout.app_name}\n" == sout

    err = _goto(app_layout.app_name)
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
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"

    c1 = app_layout._app_backend.be.changeset()
    err = _goto(app_layout.app_name, version="0.0.2")
    assert err == 1

    err = _goto(app_layout.app_name, version="1.3.0")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    captured = capfd.readouterr()
    assert (
        "[INFO] Found existing version 1.3.0 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    c2 = app_layout._app_backend.be.changeset()
    assert c1 != c2
    err = _goto(app_layout.app_name, version="1.3.1")
    assert err == 0
    c3 = app_layout._app_backend.be.changeset()
    assert c1 == c3

    err = _goto(app_layout.app_name)
    assert err == 0

    c4 = app_layout._app_backend.be.changeset()
    assert c1 == c4

    root_app_name = "some_root_app/service1"
    _init_app(root_app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc1 = app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    rc2 = app_layout._app_backend.be.changeset()

    assert rc1 != rc2

    err = _goto(root_app_name, version="1.3.0")
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_app_name)
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    assert rc2 == app_layout._app_backend.be.changeset()

    app_layout.write_file_commit_and_push("test_repo_0", "a.yxy", "msg")

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.5.0"

    rc3 = app_layout._app_backend.be.changeset()

    root_name = root_app_name.split("/")[0]

    err = _goto(root_name, version="1", root=True)
    assert err == 0

    assert rc1 == app_layout._app_backend.be.changeset()

    err = _goto(root_name, root=True)
    assert err == 0

    assert rc3 == app_layout._app_backend.be.changeset()

    err, ver_info, _ = _stamp_app(root_app_name, "minor")
    assert err == 0

    deps = ver_info["stamping"]["app"]["changesets"]

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash']}",
    )
    assert err == 0

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}",
    )
    assert err == 0

    capfd.readouterr()

    err = _goto(
        root_app_name,
        version=f"1.5.0+{deps['.']['hash'][:-10]}X",
    )
    assert err == 1

    captured = capfd.readouterr()
    assert "[ERROR] Wrong unique id\n" == captured.err


def test_stamp_on_branch_merge_squash(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("new_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout._app_backend.selected_remote.pull(rebase=True)
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0
    app_layout.write_file_commit_and_push("test_repo_0", "f3.file", "msg3")
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

    assert data["_version"] == "1.3.3"


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
        ".vmn/test_app/{}".format(vmn.VER_FILE_NAME),
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
        ".vmn/test_app/{}".format(vmn.VER_FILE_NAME),
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
        ".vmn/test_app/{}".format(vmn.VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, optional_release_mode="patch")
    assert err == 0
    _version = ver_info["stamping"]["app"]["_version"]
    assert "0.2.3-alpha9.10" == _version


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


def test_version_backends_cargo(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "Cargo.toml",
        toml.dumps({"package": {"name": "test_app", "version": "some ignored string"}}),
    )

    conf = {
        "version_backends": {"cargo": {"path": "Cargo.toml"}},
        "deps": {
            "../": {
                "test_repo_0": {
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


def test_version_backends_poetry(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "pyproject.toml",
        toml.dumps(
            {"tool": {"poetry": {"name": "test_app", "version": "some ignored string"}}}
        ),
    )

    conf = {
        "version_backends": {"poetry": {"path": "pyproject.toml"}},
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["poetry"]["path"]
    )

    with open(full_path, "r") as f:
        data = toml.load(f)
        assert data["tool"]["poetry"]["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


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


def test_version_backends_npm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "package.json",
        json.dumps({"name": "test_app", "version": "some ignored string"}),
    )

    conf = {
        "template": "[{major}][.{minor}][.{patch}]",
        "version_backends": {"npm": {"path": "package.json"}},
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

    full_path = os.path.join(
        params["root_path"], params["version_backends"]["npm"]["path"]
    )

    with open(full_path, "r") as f:
        data = json.load(f)
        assert data["version"] == "0.0.2"

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_backward_compatability_with_0_3_9_vmn(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.3.9")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app("app1", "major")
    captured = capfd.readouterr()
    assert err == 0
    assert (
        "[INFO] Found existing version 0.0.3 and nothing has changed. Will not stamp\n"
        == captured.out
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app("app1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.4"

    err = _goto("app1", version="0.0.2")
    assert err == 0

    err = _goto("app1", version="0.0.3")
    assert err == 0

    err = _goto("app1", version="0.0.4")
    assert err == 0

    err = _goto("app1")
    assert err == 0

    err, ver_info, _ = _stamp_app("root_app/service1", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


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


def test_shallow_vmn_commit_repo_stamp(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_shallow_non_vmn_commit_repo_stamp(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "connnntenctt")

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    capfd.readouterr()
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_shallow_vmn_commit_repo_stamp_pr(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch", prerelease="yuval")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-yuval.1"

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.tst",
        "bla",
    )

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1-yuval.2"


def test_same_user_tag(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "test.tst",
        "bla",
    )

    app_layout.create_tag("HEAD~3", f"{app_layout.app_name}_2.0.0")

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_perf_show(app_layout):
    import subprocess
    import shutil

    base_cmd = [
        "wget",
        "https://github.com/final-israel/vmn/releases/download/vmn_stamping_action_0.0.1/perf.tgz",
    ]
    subprocess.call(base_cmd, cwd=app_layout.base_dir)
    shutil.rmtree(app_layout.test_app_remote)
    shutil.rmtree(app_layout.repo_path)
    base_cmd = ["tar", "-xzf", "./perf.tgz"]
    subprocess.call(base_cmd, cwd=app_layout.base_dir)
    base_cmd = ["git", "clone", app_layout.test_app_remote, app_layout.repo_path]
    subprocess.call(base_cmd, cwd=app_layout.base_dir)

    import time

    t1 = time.perf_counter()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0
    t2 = time.perf_counter()
    diff = t2 - t1

    assert diff < 10


def test_run_vmn_from_non_git_repo(app_layout, capfd):
    _run_vmn_init()
    app_layout.set_working_dir(app_layout.base_dir)
    stamp_utils.VMN_LOGGER = None
    capfd.readouterr()
    ret = vmn.vmn_run([])[0]
    capfd.readouterr()
    assert ret == 1


def test_bad_tag(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.create_tag("HEAD", "Semver-foo-python3-1.1.1")

    # read to clear stderr and out
    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    capfd.readouterr()

    assert err == 0

    app_layout.create_tag("HEAD", "app_name-1.1.1")

    # read to clear stderr and out
    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    capfd.readouterr()

    assert err == 0


def test_stamp_with_removed_tags_no_commit(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    ret, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ret == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_stamp_with_removed_tags_with_commit(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    ret, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ret == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


def test_show_after_1_tag_removed(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "dirty:\n- modified\nout: 0.0.0\n\n" == captured.out


def test_show_after_multiple_tags_removed_1_tag_left(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    for i in range(4):
        app_layout.write_file_commit_and_push(
            "test_repo_0", "a/b/c/f1.file", f"{i}msg1"
        )
        _stamp_app(f"{app_layout.app_name}", "patch")
        app_layout.remove_tag(f"{app_layout.app_name}_0.0.{i + 1}")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()

    res = yaml.safe_load(captured.out)
    assert res["out"] == "0.0.0"
    assert res["dirty"][0] == "modified"


def test_show_after_multiple_tags_removed_0_tags_left(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.remove_tag(f"{app_layout.app_name}_0.0.0")

    for i in range(4):
        app_layout.write_file_commit_and_push(
            "test_repo_0", "a/b/c/f1.file", f"{i}msg1"
        )
        _stamp_app(f"{app_layout.app_name}", "patch")
        app_layout.remove_tag(f"{app_layout.app_name}_0.0.{i + 1}")

    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 1

    captured = capfd.readouterr()
    assert (
        captured.err == "[ERROR] Failed to get version info for tag: test_app_0.0.0\n"
        "[ERROR] Untracked app. Run vmn init-app first\n"
        "[ERROR] Error occured when getting the repo status\n"
    )


def test_shallow_removed_vmn_tag_repo_stamp(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    clone_path = app_layout.create_new_clone("test_repo_0", depth=1)
    app_layout.set_working_dir(clone_path)
    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


@pytest.mark.parametrize("manual_version", [("0.0.0", "0.0.1"), ("2.0.0", "2.0.1")])
def test_removed_vmn_tag_and_version_file_repo_stamp(app_layout, manual_version):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, ver_info, params = _stamp_app(f"{app_layout.app_name}", "patch")
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.remove_tag(f"{app_layout.app_name}_0.0.1")

    file_path = params["version_file_path"]

    app_layout.remove_file(file_path)
    verfile_manual_content = {
        "version_to_stamp_from": manual_version[0],
        "prerelease": "release",
        "prerelease_count": {},
    }
    # now we want to override the version by changing the file version:
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        ".vmn/test_app/{}".format(vmn.VER_FILE_NAME),
        yaml.dump(verfile_manual_content),
    )

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == manual_version[1]


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


def test_stamp_no_ff_rebase(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    other_branch = "topic"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.2" == res["out"]


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


def test_missing_local_branch(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    cur_hex = app_layout._app_backend.be.changeset()
    app_layout.checkout(cur_hex)

    app_layout.delete_branch(main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0


def test_missing_local_branch_error_scenarios(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    main_branch = app_layout._app_backend.be.get_active_branch()
    cur_hex = app_layout._app_backend.be._be.head.commit.hexsha

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    app_layout.checkout(cur_hex)
    app_layout.delete_branch(main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1

    cur_hex = app_layout._app_backend.be._be.head.commit.hexsha
    app_layout.checkout(cur_hex)

    err, ver_info, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 1


def test_double_release_works(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    captured = capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.2"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="beta")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.1"
    assert data["prerelease"] == "beta"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-beta.2"
    assert data["prerelease"] == "beta"

    for i in range(2):
        capfd.readouterr()
        err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.2")
        captured = capfd.readouterr()

        assert err == 0
        assert captured.out == "[INFO] 1.3.0\n"
        assert captured.err == ""

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0")
    captured = capfd.readouterr()

    assert err == 0
    assert captured.out == "[INFO] 1.3.0\n"
    assert captured.err == ""

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-beta.1")
    captured = capfd.readouterr()

    assert err == 1
    assert captured.err == "[ERROR] Failed to release 1.3.0-beta.1\n"
    assert captured.out == ""

    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()

    assert err == 0
    assert captured.out == "[INFO] 1.3.0\n"
    assert captured.err == ""

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")
    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()

    assert err == 1
    assert captured.out == ""
    assert (
        captured.err == "[ERROR] When running vmn release and not on a version commit, "
        "you must specify a specific version using -v flag\n"
    )


@pytest.mark.parametrize(
    "branch_name", [("new_branch", "new_branch2"), ("new_branch/a", "new_branch2/b")]
)
def test_change_of_tracking_branch(app_layout, capfd, branch_name):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    app_layout.checkout(branch_name[0], create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    app_layout.checkout(branch_name[1], create_new=True)

    app_layout.delete_branch(branch_name[0])

    app_layout._app_backend.be._be.git.branch(
        f"--set-upstream-to=origin/{branch_name[0]}", branch_name[1]
    )

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="patch")
    assert err == 0


@pytest.mark.parametrize("branch_name", ["new_branch", "new_branch/a"])
def test_no_upstream_branch_stamp(app_layout, capfd, branch_name):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    app_layout.checkout(branch_name, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="minor")
    assert err == 0

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    main_branch = app_layout._app_backend.be.get_active_branch()
    assert branch_name == main_branch

    app_layout._app_backend.be._be.git.branch("--unset-upstream", main_branch)

    err, ver_info, _ = _stamp_app(app_layout.app_name, release_mode="patch")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.1"


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


def test_dirty_no_ff_rebase(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    other_branch = "topic"

    app_layout.checkout(other_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg1")
    _stamp_app(app_layout.app_name, "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "f2.file", "msg2")
    _stamp_app(app_layout.app_name, "patch")

    app_layout.rebase(main_branch, other_branch, no_ff=True)

    # read to clear stderr and out
    capfd.readouterr()

    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    res = yaml.safe_load(captured.out)
    assert "0.1.2" == res["out"]
    assert len(res["dirty"]) == 2
    assert "modified" in res["dirty"]
    assert "outgoing" in res["dirty"]


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
    assert "modified" in res["dirty"]
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
    assert "modified" in res["dirty"]
    assert "outgoing" in res["dirty"]


def test_no_fetch_branch_configured(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "minor")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    app_layout.git_cmd(args=["config", "--unset", "remote.origin.fetch"])

    err, ver_info, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0


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


def test_show_no_log_in_stdout(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(f"{app_layout.app_name}", "patch")
    app_layout.write_file_commit_and_push("test_repo_0", "a/b/c/f1.file", "msg1")

    capfd.readouterr()
    err = _show(app_layout.app_name, raw=True)
    assert err == 0

    captured = capfd.readouterr()
    assert "dirty:\n- modified\nout: 0.0.1\n\n" == captured.out

    result = subprocess.run(
        [
            "grep",
            "-q",
            "Test logprint in show",
            os.path.join(app_layout.repo_path, ".vmn", "vmn.log"),
        ]
    )
    assert result.returncode == 0


# TODO:: add test for app release. merge squash and show. expect the newly released version


def test_two_prs_from_same_origin(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    first_branch = "first"

    app_layout.checkout(first_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{first_branch}.1"
    assert data["prerelease"] == first_branch
    app_layout.checkout(main_branch, create_new=False)
    second_branch = "second"

    app_layout.checkout(second_branch, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=second_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{second_branch}.1"
    assert data["prerelease"] == second_branch


def test_two_prs_from_same_origin_after_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    first_branch = "first"

    app_layout.checkout(first_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{first_branch}.1"
    assert data["prerelease"] == first_branch
    app_layout.checkout(main_branch, create_new=False)
    second_branch = "second"

    app_layout.checkout(second_branch, create_new=True)
    app_layout.checkout(main_branch)
    _release_app(app_layout.app_name, f"0.0.2-{first_branch}.1")
    app_layout.checkout(second_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=second_branch
    )
    capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.3-{second_branch}.1"
    assert data["prerelease"] == second_branch


def test_no_pr_happens_after_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    first_branch = "first"

    app_layout.checkout(first_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{first_branch}.1"
    assert data["prerelease"] == first_branch
    app_layout.checkout(main_branch)
    second_branch = "second"

    app_layout.checkout(second_branch, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=second_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{second_branch}.1"
    assert data["prerelease"] == second_branch

    app_layout.checkout(main_branch)
    app_layout.merge(from_rev=second_branch, to_rev=main_branch)

    err, ver_info, _ = _release_app(app_layout.app_name)
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"
    assert data["prerelease"] == "release"

    third_branch = "third"
    app_layout.checkout(third_branch, create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=third_branch
    )
    captured = capfd.readouterr()
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.3-{third_branch}.1"

    app_layout.checkout(first_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    capfd.readouterr()
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease=first_branch
    )
    captured = capfd.readouterr()
    assert (
        captured.err
        == "[ERROR] The version 0.0.2 was already released. Will refuse to stamp prerelease version\n"
    )
    assert err == 1


def test_overwrite_version_and_orm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    main_branch = app_layout._app_backend.be.get_active_branch()
    c1_branch = "c1"
    app_layout.checkout(c1_branch, create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease=c1_branch
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.0.2-{c1_branch}.1"
    assert data["prerelease"] == c1_branch

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        optional_release_mode="patch",
        prerelease=c1_branch,
        override_version="0.1.0",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"0.1.1-{c1_branch}.1"
    assert data["prerelease"] == c1_branch
    app_layout.checkout(main_branch, create_new=False)


def test_override_version(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        optional_release_mode="patch",
        prerelease="rc",
        override_version="0.1.0",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]

    assert data["_version"] == "0.1.1-rc.1"


def test_merge_version_conflict(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    # 0.0.1
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.checkout(main_branch, create_new=True)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="ab"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-ab.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="ac"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-ac.1"

    app_layout.merge(from_rev="first_branch", to_rev="second_branch")
    pass


def test_rc_after_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, "1.2.3")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, release_mode="minor", prerelease="rc"
    )

    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0-rc.1"
    assert data["prerelease"] == "rc"

    i = 0
    for i in range(5):
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")
        err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"1.3.0-rc.{i + 2}"
        assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.2")
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.3.0"
    assert data["prerelease"] == "release"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")
    captured = capfd.readouterr()
    assert err != 0
    assert captured.err.startswith("[ERROR] The version 1.3.0 was already ")

    app_layout._app_backend.be._be.delete_tag("test_app_1.3.0")

    capfd.readouterr()
    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc")

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == f"1.3.0-rc.{i + 2 + 1}"
    assert data["prerelease"] == "rc"

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.3")
    captured = capfd.readouterr()
    assert err == 1

    app_layout.pull(tags=True)

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, "1.3.0-rc.3")
    captured = capfd.readouterr()
    assert err == 1

    err = _show(app_layout.app_name, version="1.3.0", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "1.3.0-rc.2" in tmp["versions"]


def test_backward_compatability_with_0_8_4_vmn(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.8.4")

    capfd.readouterr()
    err = _show("app1", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)

    assert "1.0.0-alpha1" == tmp["version"]

    err = _show("app1", verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "1.0.0-alpha1" == tmp["version"]


def test_multi_prereleases(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name, starting_version="2.13.3")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="564"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="513"
    )

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="508"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="508"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="513"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )

    capfd.readouterr()
    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)

    assert "2.13.4-staging.2" == tmp["version"]

    err = _show(app_layout.app_name, verbose=True)
    assert err == 0

    captured = capfd.readouterr()
    tmp = yaml.safe_load(captured.out)
    assert "2.13.4-staging.2" == tmp["version"]


def test_orm_rc_from_release(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    # Actual Test
    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"


def test_orm_rc_from_release_globally_latest_other_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc1.1"
    assert data["prerelease"] == "rc1"

    # Actual Test
    app_layout.checkout(main_branch)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc2"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_rc_from_release_globally_latest_same_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    # Actual Test
    app_layout.checkout(main_branch)
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_rc_from_rc_globally_latest_release(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    main_branch = app_layout._app_backend.be.get_active_branch()

    first_branch = "first_branch"
    second_branch = "second_branch"

    branches = [first_branch, second_branch]
    for i in range(len(branches)):
        app_layout.checkout(branches[i], create_new=True)
        app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

        err, ver_info, _ = _stamp_app(
            app_layout.app_name,
            optional_release_mode="patch",
            prerelease=f"rc{i}",
        )
        assert err == 0

        data = ver_info["stamping"]["app"]
        assert data["_version"] == f"0.0.2-rc{i}.1"
        assert data["prerelease"] == f"rc{i}"

        app_layout.checkout(main_branch)

    err, ver_info, _ = _release_app(app_layout.app_name, "0.0.2-rc0.1")

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2"

    # Actual Test
    app_layout.checkout(second_branch)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 1


def test_orm_rc_from_rc_globally_latest_other_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc1.1"
    assert data["prerelease"] == "rc1"

    # Actual Test
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc2"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_rc_from_rc_globally_latest_same_rc(app_layout, capfd):
    # Prepare
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    # Actual Test
    app_layout.checkout("second_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_rc_ending_with_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"


def test_pr_rc_ending_with_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(app_layout.app_name, prerelease="rc.")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_use_override_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.0",
        optional_release_mode="patch",
        prerelease="rc",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc.1"
    assert data["prerelease"] == "rc"


def test_orm_use_override_rc_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.1-rc.1",
        optional_release_mode="patch",
        prerelease="rc",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc.2"
    assert data["prerelease"] == "rc"


def test_orm_use_override_diff_rc_in_rc(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="1.0.1-rc1.1",
        optional_release_mode="patch",
        prerelease="rc2",
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1-rc2.1"
    assert data["prerelease"] == "rc2"


def test_orm_use_override_in_stable(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1"
    assert data["prerelease"] == "rc"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, "patch", override_version="1.0.0"
    )

    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "1.0.1"


def test_orm_rc_with_strange_name_dot(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc.1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc.1.1"
    assert data["prerelease"] == "rc.1"


def test_orm_rc_with_strange_name_hyphen(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc-1"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-rc-1.1"
    assert data["prerelease"] == "rc-1"


def test_orm_rc_with_strange_name_underscore(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.checkout("first_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="rc_1"
    )
    assert err == 1


def test_jenkins_checkout(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout("new_branch", create_new=True)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")
    app_layout.checkout_jekins(main_branch)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"


def test_problem_found_in_real_customer(app_layout, capfd):
    app_layout.stamp_with_previous_vmn("0.8.5rc2")

    err, ver_info, _ = _stamp_app(
        "app1", optional_release_mode="patch", prerelease="189."
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "2.3.2-189.1"
    assert data["prerelease"] == "189"


def test_jenkins_checkout_branch_name_order_edge_case(app_layout, capfd):
    # When running in jenkins repo, the remote branch gets deleted.
    # Vmn tries to find to correct remote brach using the command "git branch -r HEAD".
    # It returns a list, and we must choose the right branch, not just the first of the list.
    # The following test creates a branch with a name above 'master' alphabetically,
    # And we should still choose master as our rightful remote
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.1"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout(
        "a_branch", create_new=True
    )  # The name of the branch is critical because it affect "git branch -r HEAD" list order

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg3")
    app_layout.checkout_jekins(main_branch)

    err, ver_info, _ = _stamp_app(f"{app_layout.app_name}", "patch")
    assert err == 0
    assert ver_info["stamping"]["app"]["_version"] == "0.0.2"


# Test overwrite in orm mode:
# 1. create app
# 2. stamp rc 0.0.1-staging.1
# 3. change something
# 4. stamp rc 0.0.2-staging.2 with overwrite with param 0.0.2-staging.1
def test_overwrite_with_orm_from_orm(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.1"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="0.0.3-staging.1",
        optional_release_mode="patch",
        prerelease="staging",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.3-staging.2"
    assert data["prerelease"] == "staging"


def test_overwrite_with_orm_from_stable(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    app_layout._app_backend.be.get_active_branch()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.1"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name, optional_release_mode="patch", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.2-staging.2"
    assert data["prerelease"] == "staging"

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg0")

    err, ver_info, _ = _stamp_app(
        app_layout.app_name,
        override_version="0.0.2",
        optional_release_mode="patch",
        prerelease="staging",
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.0.3-staging.1"
    assert data["prerelease"] == "staging"


def test_release_branch_policy(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "text")

    conf = {
        "policies": {"whitelist_release_branches": ["main", "master"]},
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    main_branch = app_layout._app_backend.be.get_active_branch()
    app_layout.checkout("new_branch", create_new=True)
    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg1")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 1

    captured = capfd.readouterr()
    assert (
        captured.err
        == "[ERROR] Policy: whitelist_release_branches was violated. Refusing to stamp\n"
    )

    capfd.readouterr()
    err, ver_info, params = _stamp_app(
        app_layout.app_name, "patch", prerelease="staging"
    )
    assert err == 0

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(app_layout.app_name)
    assert err == 0

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name, version="0.0.3-staging.1")
    assert err == 1
    captured = capfd.readouterr()
    assert captured.err.startswith(
        "[ERROR] Policy: whitelist_release_branches was violated. Refusing to release"
    )

    app_layout.checkout(main_branch)

    app_layout.write_file_commit_and_push("test_repo_0", "f1.file", "msg2")

    capfd.readouterr()
    err, ver_info, params = _stamp_app(
        app_layout.app_name, "patch", prerelease="staging"
    )
    assert err == 0

    err, ver_info, _ = _release_app(app_layout.app_name, version="0.0.3-staging.1")
    assert err == 1

    capfd.readouterr()
    err, ver_info, _ = _release_app(app_layout.app_name)
    captured = capfd.readouterr()
    assert err == 0

@pytest.mark.parametrize("default_release_mode,separate,first_commit_msg,first_expected_version,second_commit_msg,second_expected_version",
                         [
                             # Simple recognize release
                             ("", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Simple recognize optional release
                             ("optional", False, "fix: a", "0.0.2-staging.1", None, None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", None, None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", None, None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", None, None),
                             # Recognize release same version types
                             ("", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize optional release same version types
                             ("optional", False, "fix: a", "0.0.2-staging.1", "fix: a", None),
                             ("optional", False, "feat: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix!: a", None),
                             # Recognize release different version types
                             ("", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize optional release different version types
                             ("optional", False, "fix: a", "0.1.0-staging.1", "feat: a", None),
                             ("optional", False, "feat: a", "1.0.0-staging.1", "BREAKING CHANGE: a", None),
                             ("optional", False, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", None),
                             ("optional", False, "fix!: a", "1.0.0-staging.1", "fix: a", None),
                             # Recognize release same version types
                             ("", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.3-staging.1"),
                             ("", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.2.0-staging.1"),
                             ("", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "2.0.0-staging.1"),
                             ("", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             # Recognize optional release same version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "fix: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "feat: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             # Recognize release different version types
                             ("", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.1.0-staging.1"),
                             ("", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "1.0.0-staging.1"),
                             ("", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "2.0.0-staging.1"),
                             ("", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.1-staging.1"),
                             # Recognize optional release different version types
                             ("optional", True, "fix: a", "0.0.2-staging.1", "feat: a", "0.0.2-staging.2"),
                             ("optional", True, "feat: a", "0.1.0-staging.1", "BREAKING CHANGE: a", "0.1.0-staging.2"),
                             ("optional", True, "BREAKING CHANGE: a", "1.0.0-staging.1", "fix!: a", "1.0.0-staging.2"),
                             ("optional", True, "fix!: a", "1.0.0-staging.1", "fix: a", "1.0.0-staging.2"),
                          ])
def test_conventional_commits(app_layout, capfd, default_release_mode, separate, first_commit_msg, first_expected_version, second_commit_msg, second_expected_version):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "conventional_commits": {
            "default_release_mode": default_release_mode,
        }
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    first_commit_msg += """prevent racing of requests

    Introduce a request id and a reference to latest request. Dismiss
    incoming responses other than from latest request.

    Remove timeouts which were used to mitigate the racing issue but are
    obsolete now.

    Reviewed-by: Z
    Refs: #123
        """

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg=first_commit_msg
    )

    if second_commit_msg is not None:
        second_commit_msg += """prevent racing of requests

                    Introduce a request id and a reference to latest request. Dismiss
                    incoming responses other than from latest request.

                    Remove timeouts which were used to mitigate the racing issue but are
                    obsolete now.

                    Reviewed-by: Z
                    Refs: #123
                        """

        if not separate:
            app_layout.write_file_commit_and_push(
                "test_repo_0", "f1.txt", "text", commit_msg=second_commit_msg
            )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == first_expected_version
    assert data["prerelease"] == "staging"

    if second_commit_msg is None or not separate:
        return

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg=second_commit_msg
    )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == second_expected_version
    assert data["prerelease"] == "staging"

@pytest.mark.parametrize("default_release_mode", ["","optional",])
def test_conventional_commits_simple_failure(app_layout, capfd, default_release_mode):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "conventional_commits": {
            "default_release_mode": default_release_mode,
        }
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="doc: a"
    )

    err, ver_info, params = _stamp_app(app_layout.app_name, prerelease="staging")
    assert err == 1
    captured = capfd.readouterr()
    assert (
        "[ERROR] When not in release candidate mode, a release mode must be "
        "specified - use -r/--release-mode with one of major/minor/patch/hotfix\n"
        == captured.err
    )

@pytest.mark.parametrize("default_release_mode", ["","optional",])
def test_conventional_commits_simple_overwrite(app_layout, capfd, default_release_mode):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, params = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    conf = {
        "conventional_commits": {
            "default_release_mode": default_release_mode,
        }
    }

    app_layout.write_conf(params["app_conf_path"], **conf)

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "text", commit_msg="fix: a"
    )

    err, ver_info, params = _stamp_app(
        app_layout.app_name, "minor", prerelease="staging"
    )
    assert err == 0
    data = ver_info["stamping"]["app"]
    assert data["_version"] == "0.1.0-staging.1"
    assert data["prerelease"] == "staging"


def test_jinja2_gen_rn_simple(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()
    commit_msg = """fix: prevent racing of requests"""

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "content", commit_msg=commit_msg
    )

    jinja2_content = "{{release_notes}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath)
    assert err == 0

    with open(opath, "r") as f:
        assert "prevent racing of requests" in f.read().lower()


def test_jinja2_gen_rn_custom_file(app_layout, capfd):
    _run_vmn_init()
    _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    commit_msg = """fix: prevent racing of requests"""

    app_layout.write_file_commit_and_push(
        "test_repo_0", "f1.txt", "content", commit_msg=commit_msg
    )

    jinja2_content = "VERSION: {{version}}\n" "Release Notes: {{release_notes}}\n"
    app_layout.write_file_commit_and_push("test_repo_0", "f1.jinja2", jinja2_content)

    custom_keys_content = "release_notes_conf_path: cliffconf.toml\n"
    app_layout.write_file_commit_and_push(
        "test_repo_0", "custom.yml", custom_keys_content
    )

    tpath = os.path.join(app_layout._repos["test_repo_0"]["path"], "f1.jinja2")
    custom_path = os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "jinja_out.txt")
    err = _gen(app_layout.app_name, tpath, opath, custom_path=custom_path)
    assert err == 0

    with open(opath, "r") as f:
        assert "prevent racing of requests" in f.read().lower()


def test_version_backends_generic_selectors_jinja_file_with_jinja_expr(app_layout, capfd):
    _run_vmn_init()
    _, _, params = _init_app(app_layout.app_name)

    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    assert err == 0

    # read to clear stderr and out
    capfd.readouterr()

    app_layout.write_file_commit_and_push("test_repo_0", "f1.txt", "content")

    # Simulate a file that is a jinja template with a jinja expression that will fail
    jinja_expr_content = (
        'INTEGRATION_LAB: "{{ lookup(\'env\', \'INTEGRATION_LAB\') | default(false) }}"\n'
        'version: 1.0.2\nCustom: 3\n'
    )
    app_layout.write_file_commit_and_push(
        "test_repo_0",
        "in.txt",
        jinja_expr_content,
    )

    generic_selectors = {
        "generic_selectors": [
            {
                "paths_section": [
                    {
                        "input_file_path": "in.txt",
                        "output_file_path": "in.txt",
                    }
                ],
                "selectors_section": [
                    {
                        "regex_selector": f"(version: ){stamp_utils._VMN_VERSION_REGEX}",
                        "regex_sub": r"\1{{version}}",
                    },
                ],
            },
        ]
    }

    conf = {"version_backends": generic_selectors}

    app_layout.write_conf(params["app_conf_path"], **conf)

    os.path.join(app_layout._repos["test_repo_0"]["path"], "custom.yml")
    opath = os.path.join(app_layout._repos["test_repo_0"]["path"], "in.txt")

    capfd.readouterr()
    # Run the stamp and check for nonzero error code and error message in stderr
    err, _, _ = _stamp_app(app_layout.app_name, "patch")
    captured = capfd.readouterr()
    assert ("lookup" not in captured.err and "undefined" not in captured.err)

    assert err == 0

    # Check the output file: version should be replaced, lookup should be preserved
    with open(opath, "r") as f:
        content = f.read()
        assert 'INTEGRATION_LAB: "{{ lookup(\'env\', \'INTEGRATION_LAB\') | default(false) }}"' in content
        assert 'version: 0.0.2' in content

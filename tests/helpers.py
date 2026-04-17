import os
import re

from version_stamp.backends.base import VMNBackend
from version_stamp.cli.entry import vmn_run
from version_stamp.core.constants import (
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
)
from version_stamp.core.logging import reset_logger

DEV_VERSION_RE = re.compile(r"^.+-dev\.[0-9a-f]{7}\.[0-9a-f]{7}$")


def extract_dev_verstr(output):
    """Extract a dev version string from output that may contain [INFO] lines."""
    for line in output.strip().split("\n"):
        line = line.strip()
        if line.startswith("["):
            continue
        if DEV_VERSION_RE.match(line):
            return line
    return None


def _run_vmn_init():
    reset_logger()
    ret = vmn_run(["init"])[0]
    return ret


def _init_app(app_name, starting_version="0.0.0"):
    cmd = ["init-app", "-v", starting_version, app_name]
    reset_logger()
    ret, vmn_ctx = vmn_run(cmd)

    tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
        app_name, type=RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE
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


def _release_app(app_name, version=None, stamp=False):
    cmd = ["release", app_name]
    if version:
        cmd.extend(["-v", version])
    if stamp:
        cmd.append("--stamp")

    reset_logger()
    ret, vmn_ctx = vmn_run(cmd)

    vmn_ctx.vcs.initialize_backend_attrs()

    if version is None:
        tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
            app_name, type=RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE
        )
    else:
        tag_name, ver_infos = vmn_ctx.vcs.get_version_info_from_verstr(
            VMNBackend.get_base_vmn_version(
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

    reset_logger()
    ret, vmn_ctx = vmn_run(args_list)

    if vmn_ctx is None:
        return ret, None, {}

    tag_name, ver_infos = vmn_ctx.vcs.get_first_reachable_version_info(
        app_name, type=RELATIVE_TO_CURRENT_VCS_POSITION_TYPE
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
    dev=False,
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
    if dev:
        args_list.append("--dev")

    args_list.append(app_name)

    reset_logger()
    ret = vmn_run(args_list)

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

    reset_logger()
    ret = vmn_run(args_list)[0]

    return ret


def _goto(app_name, version=None, root=False):
    args_list = ["goto"]
    if version is not None:
        args_list.extend(["--version", f"{version}"])
    if root:
        args_list.append("--root")

    args_list.append(app_name)

    reset_logger()
    ret = vmn_run(args_list)[0]

    return ret


def _snapshot(app_name, action="create", version=None, note=None,
              to_version=None, tool=None, output=None,
              meta=None, meta_file=None, filter_args=None, latest=False):
    args_list = ["snapshot"]
    if action != "create":
        args_list.append(action)
    args_list.append(app_name)
    if version is not None:
        args_list.extend(["--version", version])
    if note is not None:
        args_list.extend(["--note", note])
    if to_version is not None:
        args_list.extend(["--to", to_version])
    if tool is not None:
        args_list.extend(["--tool", tool])
    if output is not None:
        args_list.extend(["--output", output])
    if meta:
        for m in meta:
            args_list.extend(["--meta", m])
    if meta_file is not None:
        args_list.extend(["--meta-file", meta_file])
    if filter_args:
        for f in filter_args:
            args_list.extend(["--filter", f])
    if latest:
        args_list.append("--latest")

    reset_logger()
    return vmn_run(args_list)[0]


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

    reset_logger()
    ret = vmn_run(args_list)[0]

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


def _experiment(app_name, action="create", version=None, note=None,
                metrics=None, file=None, attach=None, sort=None,
                top=None, latest=None, tool=None, output=None,
                keep=None, older_than=None, command="experiment"):
    args_list = [command]
    if action != "create":
        args_list.append(action)
    args_list.append(app_name)
    if version is not None:
        if isinstance(version, list):
            for v in version:
                args_list.extend(["-v", v])
        else:
            args_list.extend(["-v", version])
    if note is not None:
        args_list.extend(["--note", note])
    if metrics is not None:
        args_list.append("--metrics")
        args_list.extend(metrics)
    if file is not None:
        args_list.extend(["-f", file])
    if attach is not None:
        args_list.extend(["--attach", attach])
    if sort is not None:
        args_list.extend(["--sort", sort])
    if top is not None:
        args_list.extend(["--top", str(top)])
    if latest is not None:
        if isinstance(latest, int) and latest > 1:
            args_list.extend(["--latest", str(latest)])
        else:
            args_list.append("--latest")
    if tool is not None:
        args_list.extend(["--tool", tool])
    if output is not None:
        args_list.extend(["-o", output])
    if keep is not None:
        args_list.extend(["--keep", str(keep)])
    if older_than is not None:
        args_list.extend(["--older-than", older_than])

    reset_logger()
    return vmn_run(args_list)[0]


def _exp(app_name, **kwargs):
    return _experiment(app_name, command="exp", **kwargs)


def _configure_empty_conf(app_layout, params):
    conf = {"deps": {}, "extra_info": False}
    app_layout.write_conf(params["app_conf_path"], **conf)

    return conf

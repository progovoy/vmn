#!/usr/bin/env python3
"""Display, generation, and repository navigation functions."""
import copy
import os
import subprocess
from multiprocessing import Pool

import yaml

from version_stamp.backends.base import VMNBackend
from version_stamp.backends.factory import get_client
from version_stamp.backends.git import GitBackend
from version_stamp.core.constants import (
    POOL_SIZE_CLONES,
    POOL_SIZE_UPDATES,
    RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE,
    VMN_BE_TYPE_GIT,
)
from version_stamp.core.logging import VMN_LOGGER, init_stamp_logger, measure_runtime_decorator
from version_stamp.core.utils import resolve_root_path
from version_stamp.cli.constants import LOG_FILENAME
from version_stamp.stamping.publisher import VersionControlStamper
from version_stamp.stamping.template_data import create_data_dict_for_jinja2, gen_jinja2_template_from_data


@measure_runtime_decorator
def show(vcs, params, verstr=None):
    from version_stamp.cli.commands import _get_repo_status

    dirty_states = None
    # TODO:: fix recusrion crash when doing copy.deepcopy(vcs.ver_infos_from_repo)
    ver_infos = vcs.ver_infos_from_repo
    tag_name = vcs.selected_tag
    if verstr:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(verstr)

    if not params["from_file"]:
        expected_status = {"repo_tracked", "app_tracked"}
        optional_status = {
            "repos_exist_locally",
            "detached",
            "pending",
            "outgoing",
            "version_not_matched",
            "dirty_deps",
            "deps_synced_with_conf",
        }
        status = _get_repo_status(vcs, expected_status, optional_status)
        if status.error:
            VMN_LOGGER.error("Error occured when getting the repo status")
            VMN_LOGGER.debug(status, exc_info=True)

            raise RuntimeError()

        if tag_name in ver_infos:
            dirty_states = list(get_dirty_states(optional_status, status))

            if params["ignore_dirty"]:
                dirty_states = None

            vers = []
            for i in ver_infos.keys():
                vers.append(i.split("_")[-1])

            ver_infos[tag_name]["ver_info"]["stamping"]["app"]["versions"] = []
            ver_infos[tag_name]["ver_info"]["stamping"]["app"]["versions"].extend(vers)

    if tag_name not in ver_infos:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]

    if ver_info is None:
        VMN_LOGGER.error(
            "Version information was not found " "for {0}.".format(vcs.name)
        )

        raise RuntimeError()

    # Done resolving ver_info. Move it to separate function

    data = {}
    if params["conf"]:
        if not vcs.root_context:
            data["conf"] = {
                "raw_deps": copy.deepcopy(vcs.raw_configured_deps),
                "deps": copy.deepcopy(vcs.configured_deps),
                "template": vcs.template,
                "hide_zero_hotfix": vcs.hide_zero_hotfix,
                "version_backends": copy.deepcopy(vcs.version_backends),
            }
        else:
            data["conf"] = {
                "external_services": vcs.external_services,
            }

    if params.get("display_type"):
        data["type"] = ver_info["stamping"]["app"]["prerelease"]

    if params.get("dev") and not params["from_file"] and dirty_states:
        try:
            from version_stamp.cli.snapshot import _compute_diff_hash

            commit_hash = vcs.backend.changeset()[:7]
            diff_output = vcs.backend._be.git.diff("HEAD")
            diff_hash = _compute_diff_hash(diff_output)
            params["_dev_commit"] = commit_hash
            params["_dev_diff_hash"] = diff_hash
        except Exception:
            VMN_LOGGER.debug("Failed to compute dev hashes", exc_info=True)

    if vcs.root_context:
        out = _handle_root_output_to_user(data, dirty_states, params, vcs, ver_info)
    else:
        out = _handle_output_to_user(
            data, dirty_states, params, tag_name, vcs, ver_info
        )

    print(out)

    return out


def _build_dev_version(base_version, dev_commit, dev_diff_hash):
    return f"{base_version}-dev.{dev_commit}.{dev_diff_hash}"


def _handle_output_to_user(data, dirty_states, params, tag_name, vcs, ver_info):
    data.update(ver_info["stamping"]["app"])
    props = VMNBackend.deserialize_vmn_tag_name(tag_name)
    verstr = props.verstr
    data["version"] = VMNBackend.get_utemplate_formatted_version(
        verstr, vcs.template, vcs.hide_zero_hotfix
    )
    data["unique_id"] = VMNBackend.gen_unique_id(
        verstr, data["changesets"]["."]["hash"]
    )
    is_dev = params.get("dev") and params.get("_dev_commit") and dirty_states

    if params.get("verbose"):
        if dirty_states:
            data["dirty"] = dirty_states
        if is_dev:
            data["dev_version"] = _build_dev_version(
                data["version"], params["_dev_commit"], params["_dev_diff_hash"]
            )
        out = yaml.dump(data)
    else:
        out = data["version"]

        if params.get("raw"):
            out = data["_version"]

        if params.get("display_unique_id"):
            out = VMNBackend.gen_unique_id(
                out, data["changesets"]["."]["hash"]
            )

        if is_dev:
            out = _build_dev_version(
                out, params["_dev_commit"], params["_dev_diff_hash"]
            )

        d_out = {}
        if dirty_states and not is_dev:
            d_out.update(
                {
                    "out": out,
                    "dirty": dirty_states,
                }
            )
        if params.get("display_type"):
            d_out.update(
                {
                    "out": out,
                    "type": data["prerelease"],
                }
            )

        if params.get("conf"):
            d_out.update(
                {
                    "out": out,
                    "conf": data["conf"],
                }
            )

        if d_out:
            out = yaml.safe_dump(d_out)

    return out


def _handle_root_output_to_user(data, dirty_states, params, vcs, ver_info):
    if "root_app" not in ver_info["stamping"]:
        err_str = f"App {vcs.name} does not have a root app"
        VMN_LOGGER.error(err_str)

        raise RuntimeError()

    data.update(ver_info["stamping"]["root_app"])
    is_dev = params.get("dev") and params.get("_dev_commit") and dirty_states

    out = None
    if params.get("verbose"):
        if dirty_states:
            data["dirty"] = dirty_states
        if is_dev:
            data["dev_version"] = _build_dev_version(
                str(data["version"]), params["_dev_commit"], params["_dev_diff_hash"]
            )

        out = yaml.dump(data)
    else:
        out = data["version"]

        if is_dev:
            out = _build_dev_version(
                str(out), params["_dev_commit"], params["_dev_diff_hash"]
            )

        d_out = {}
        if dirty_states and not is_dev:
            d_out.update(
                {
                    "out": out,
                    "dirty": dirty_states,
                }
            )
        if params.get("display_type"):
            d_out.update(
                {
                    "out": out,
                    "type": data["type"],
                }
            )

        if params.get("conf"):
            d_out.update(
                {
                    "out": out,
                    "conf": data["conf"],
                }
            )

        if d_out:
            out = yaml.safe_dump(d_out)

    return out


@measure_runtime_decorator
def gen(vcs, params, verstr_range=None):
    from version_stamp.cli.commands import _get_repo_status

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally",
        "detached",
        "pending",
        "outgoing",
        "version_not_matched",
        "dirty_deps",
        "deps_synced_with_conf",
    }
    status = _get_repo_status(vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.error("Error occured when getting the repo status")
        VMN_LOGGER.debug(status, exc_info=True)

        raise RuntimeError()

    verstr, end_verstr = None, "HEAD"
    end_tag_name = end_verstr
    # Check if the version string contains a range (two dots)
    if verstr_range is not None and ".." in verstr_range:
        verstr, end_verstr = verstr_range.split("..")
    else:
        verstr = verstr_range

    if end_verstr != "HEAD":
        end_tag_name, _ = vcs.get_version_info_from_verstr(end_verstr)

    if verstr is None:
        ver_infos = vcs.ver_infos_from_repo
        tag_name = vcs.selected_tag
    else:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(verstr)

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        VMN_LOGGER.error(
            "Version information was not found " "for {0}.".format(vcs.name)
        )

        raise RuntimeError()

    dirty_states = get_dirty_states(optional_status, status)
    if params["verify_version"]:
        # TODO: check here what will happen when using "hotfix" octa
        if dirty_states:
            VMN_LOGGER.error(
                f"The repository and maybe some of its dependencies are in dirty state."
                f"Dirty states found: {dirty_states}.\nError messages collected for dependencies:\n"
                f"{status.err_msgs['dirty_deps']}\n"
                f"Refusing to gen."
            )
            raise RuntimeError()

        if (
            status.matched_version_info is not None
            and verstr is not None
            # TODO:: check this statement
            and status.matched_version_info["stamping"]["app"]["_version"] != verstr
        ):
            VMN_LOGGER.error(
                f"The repository is not exactly at version: {verstr}. "
                f"You can use `vmn goto` in order to jump to that version.\n"
                f"Refusing to gen."
            )
            raise RuntimeError()

    data = ver_infos[tag_name]["ver_info"]["stamping"]["app"]

    # With verstr given, we know the supposed to be deps states.
    # If no verstr given, learn the actual deps state
    if verstr is None:
        data["changesets"] = {}

        for k, v in vcs.configured_deps.items():
            if k not in vcs.actual_deps_state:
                VMN_LOGGER.error(
                    f"{k} doesn't exist locally. Use vmn goto and rerun"
                )
                raise RuntimeError()

            data["changesets"][k] = copy.deepcopy(vcs.actual_deps_state[k])
            data["changesets"][k]["state"] = {"clean"}

            if status.repos and vcs.repo_name != k:
                data["changesets"][k]["state"] = status.repos[k]["state"]
            elif vcs.repo_name == k:
                data["changesets"][k]["state"] = dirty_states

    data["version"] = VMNBackend.get_utemplate_formatted_version(
        data["_version"], vcs.template, vcs.hide_zero_hotfix
    )

    data["base_version"] = VMNBackend.get_base_vmn_version(
        data["_version"],
        vcs.hide_zero_hotfix,
    )

    tmplt_value = create_data_dict_for_jinja2(
        tag_name,
        end_tag_name,
        vcs.backend.repo_path,
        ver_infos[tag_name]["ver_info"],
        params["custom_values"],
    )

    gen_jinja2_template_from_data(
        tmplt_value,
        params["jinja_template"],
        params["output"],
    )

    return 0


def get_dirty_states(optional_status, status):
    dirty_states = (optional_status & status.state) | {
        "repos_exist_locally",
        "detached",
    }
    dirty_states -= {"detached", "repos_exist_locally", "deps_synced_with_conf"}

    try:
        debug_msg = ""
        for k in status.err_msgs.keys():
            if k in dirty_states:
                debug_msg = f"{debug_msg}\n{status.err_msgs[k]}"

        if debug_msg:
            VMN_LOGGER.debug(f"Debug for dirty states call:{debug_msg}")
    except Exception:
        VMN_LOGGER.debug("Logged Exception message: ", exc_info=True)
        pass

    return dirty_states


def _goto_dev_version(vcs, params, version):
    """Handle goto for dev versions: checkout base commit + apply snapshot patches."""
    from version_stamp.cli.snapshot import LocalSnapshotStorage

    storage = LocalSnapshotStorage(vcs.vmn_root_path)
    metadata, patches = storage.load(vcs.name, version)

    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {version} not found locally")
        return 1

    base_commit = metadata["base_commit"]

    if not params.get("deps_only"):
        try:
            vcs.backend.checkout(rev=base_commit)
        except Exception:
            VMN_LOGGER.error(
                f"Failed to checkout base commit {base_commit[:7]}"
            )
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            return 1

        if patches.get("local_commits"):
            result = subprocess.run(
                ["git", "am", "--3way"],
                input=patches["local_commits"],
                capture_output=True, text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply local commits patch: {result.stderr}"
                )
                return 1

        if patches.get("working_tree"):
            result = subprocess.run(
                ["git", "apply", "--3way"],
                input=patches["working_tree"],
                capture_output=True, text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply working tree patch: {result.stderr}"
                )
                return 1

    VMN_LOGGER.info(f"Restored dev version {version} of {vcs.name}")
    return 0


@measure_runtime_decorator
def goto_version(vcs, params, version, pull):
    unique_id = None
    check_unique = False
    status_str = ""

    # Handle dev versions via snapshot restore
    if version is not None and "-dev." in version:
        return _goto_dev_version(vcs, params, version)

    if version is None:
        if not params["deps_only"]:
            ret = vcs.backend.checkout_branch()
            assert ret is not None

            if pull:
                try:
                    vcs.retrieve_remote_changes()
                except Exception:
                    VMN_LOGGER.error(
                        "Failed to pull, run with --debug for more details"
                    )
                    VMN_LOGGER.debug(
                        "Logged Exception message:", exc_info=True
                    )

                    return 1

                ret = vcs.backend.checkout_branch()
                assert ret is not None

            del vcs
            vcs = VersionControlStamper(params)

        tag_name, ver_infos = vcs.get_first_reachable_version_info(
            vcs.name, vcs.root_context, RELATIVE_TO_CURRENT_VCS_BRANCH_TYPE
        )

        vcs.enhance_ver_info(ver_infos)

        if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
            VMN_LOGGER.error(f"No such app: {vcs.name}")
            return 1

        data = ver_infos[tag_name]["ver_info"]["stamping"]["app"]
        deps = copy.deepcopy(vcs.configured_deps)

        if not params["deps_only"]:
            if vcs.root_context:
                verstr = ver_infos[tag_name]["ver_info"]["stamping"]["root_app"][
                    "version"
                ]
                status_str = f"You are at the tip of the branch of version {verstr} for {vcs.name}"
            else:
                status_str = f"You are at the tip of the branch of version {data['_version']} for {vcs.name}"
    else:
        # check for unique id
        res = version.split("+")
        if len(res) > 1:
            version, unique_id = res
            check_unique = True

        if not params["deps_only"] and pull:
            try:
                vcs.retrieve_remote_changes()
            except Exception:
                VMN_LOGGER.error(
                    "Failed to pull, run with --debug for more details"
                )
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

                return 1

        tag_name, ver_infos = vcs.get_version_info_from_verstr(version)
        if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
            VMN_LOGGER.error(f"No such app: {vcs.name}")
            return 1

        data = ver_infos[tag_name]["ver_info"]["stamping"]["app"]
        deps = copy.deepcopy(data["changesets"])

        if not params["deps_only"]:
            try:
                vcs.backend.checkout(tag=tag_name)
                status_str = f"You are at version {version} of {vcs.name}"
            except Exception:
                VMN_LOGGER.error(
                    "App: {0} with version: {1} was "
                    "not found".format(vcs.name, version)
                )

                return 1

    if check_unique:
        if not deps["."]["hash"].startswith(unique_id):
            VMN_LOGGER.error("Wrong unique id")
            return 1

    deps.pop(".")
    if deps:
        if version is None:
            for rel_path, v in deps.items():
                v["hash"] = None

                if "branch" in vcs.configured_deps[rel_path]:
                    v["branch"] = vcs.configured_deps[rel_path]["branch"]
                if "tag" in vcs.configured_deps[rel_path]:
                    v["branch"] = None
                    v["tag"] = vcs.configured_deps[rel_path]["tag"]
                if "hash" in vcs.configured_deps[rel_path]:
                    v["branch"] = None
                    v["tag"] = None
                    v["hash"] = vcs.configured_deps[rel_path]["hash"]
        try:
            _goto_version(deps, vcs.vmn_root_path, pull)
        except Exception as exc:
            VMN_LOGGER.error(f"goto failed: {exc}")
            VMN_LOGGER.debug("", exc_info=True)

            return 1

    if status_str:
        VMN_LOGGER.info(status_str)

    return 0


@measure_runtime_decorator
def _update_repo(args):
    root_path = resolve_root_path()
    vmn_path = os.path.join(root_path, ".vmn")

    init_stamp_logger(os.path.join(vmn_path, LOG_FILENAME))

    path, rel_path, branch_name, tag, changeset, pull = args

    client = None
    try:
        if path == root_path:
            client, err = get_client(path, VMN_BE_TYPE_GIT, inherit_env=True)
        else:
            client, err = get_client(path, VMN_BE_TYPE_GIT)

        # TODO:: why this is not an error?
        if client is None:
            return {"repo": rel_path, "status": 0, "description": err}
    except Exception:
        VMN_LOGGER.exception(
            "Unexpected behaviour:\nAborting update " f"operation in {path} Reason:\n"
        )

        return {"repo": rel_path, "status": 1, "description": None}

    try:
        err = client.check_for_pending_changes()
        if err:
            VMN_LOGGER.info("{0}. Aborting update operation ".format(err))
            return {"repo": rel_path, "status": 1, "description": err}

    except Exception:
        VMN_LOGGER.debug(f'Skipping "{path}"')
        VMN_LOGGER.debug("Exception info: ", exc_info=True)

        return {"repo": rel_path, "status": 0, "description": None}

    cur_changeset = client.changeset()
    try:
        if not client.in_detached_head():
            err = client.check_for_outgoing_changes()
            if err:
                VMN_LOGGER.info(
                    "{0}. Aborting update operation".format(err)
                )
                return {"repo": rel_path, "status": 1, "description": err}

        VMN_LOGGER.info("Updating {0}".format(rel_path))

        if pull:
            try:
                client.checkout_branch()
                client.pull()
            except Exception:
                VMN_LOGGER.exception("Failed to pull:", exc_info=True)
                return {"repo": rel_path, "status": 1, "description": "Failed to pull"}

        if changeset is None:
            if tag is not None:
                client.checkout(tag=tag)
                VMN_LOGGER.info(
                    "Updated {0} to tag {1}".format(rel_path, tag)
                )
            else:
                rev = client.checkout_branch(branch_name=branch_name)
                if rev is None:
                    raise RuntimeError(f"Failed to checkout to branch {branch_name}")

                if branch_name is not None:
                    VMN_LOGGER.info(
                        "Updated {0} to branch {1}".format(rel_path, branch_name)
                    )
                else:
                    VMN_LOGGER.info(
                        "Updated {0} to changeset {1}".format(rel_path, rev)
                    )
        else:
            client.checkout(rev=changeset)

            VMN_LOGGER.info(
                "Updated {0} to {1}".format(rel_path, changeset)
            )
    except Exception:
        VMN_LOGGER.exception(
            f"Unexpected behaviour:\n"
            f"Trying to abort update operation in {path} "
            "Reason:\n",
            exc_info=True,
        )

        try:
            client.checkout(rev=cur_changeset)
        except Exception:
            VMN_LOGGER.exception(
                "Unexpected behaviour when tried to revert:", exc_info=True
            )

        return {"repo": rel_path, "status": 1, "description": None}

    return {"repo": rel_path, "status": 0, "description": None}


@measure_runtime_decorator
def _clone_repo(args):
    root_path = resolve_root_path()
    vmn_path = os.path.join(root_path, ".vmn")

    init_stamp_logger(os.path.join(vmn_path, LOG_FILENAME))

    path, rel_path, remote, vcs_type = args
    if os.path.exists(path):
        return {"repo": rel_path, "status": 0, "description": None}

    VMN_LOGGER.info("Cloning {0}..".format(rel_path))
    try:
        if vcs_type == VMN_BE_TYPE_GIT:
            GitBackend.clone(path, remote)
    except Exception as exc:
        try:
            s = "already exists and is not an empty directory."
            if s in str(exc):
                return {"repo": rel_path, "status": 0, "description": None}
        except Exception:
            pass

        err = "Failed to clone {0} repository. " "Description: {1}".format(
            rel_path, exc.args
        )
        return {"repo": rel_path, "status": 1, "description": err}

    return {"repo": rel_path, "status": 0, "description": None}


@measure_runtime_decorator
def _goto_version(deps, vmn_root_path, pull):
    args = []
    for rel_path, v in deps.items():
        if "remote" not in v or not v["remote"]:
            VMN_LOGGER.error(
                "Failed to find a remote for a configured repository. Failing goto"
            )
            raise RuntimeError()

        # In case the remote is a local dir
        if v["remote"].startswith("."):
            v["remote"] = os.path.join(vmn_root_path, v["remote"])

        args.append(
            (
                os.path.join(vmn_root_path, rel_path),
                rel_path,
                v["remote"],
                v["vcs_type"],
            )
        )
    with Pool(min(len(args), POOL_SIZE_UPDATES)) as p:
        results = p.map(_clone_repo, args)

    err = False
    failed_repos = set()
    for res in results:
        if res["status"] == 1:
            err = True

            if res["repo"] is None and res["description"] is None:
                continue

            msg = "Failed to clone "
            if res["repo"] is not None:
                failed_repos.add(res["repo"])
                msg += "from {0} ".format(res["repo"])
            if res["description"] is not None:
                msg += "because {0}".format(res["description"])

            VMN_LOGGER.info(msg)

    args = []
    for rel_path, v in deps.items():
        if rel_path in failed_repos:
            continue

        branch = None
        if "branch" in v and v["branch"] is not None:
            branch = v["branch"]
        tag = None
        if "tag" in v and v["tag"] is not None:
            tag = v["tag"]

        args.append(
            (
                os.path.join(vmn_root_path, rel_path),
                rel_path,
                branch,
                tag,
                v["hash"],
                pull,
            )
        )

    with Pool(min(len(args), POOL_SIZE_CLONES)) as p:
        results = p.map(_update_repo, args)

    for res in results:
        if res["status"] == 1:
            err = True
            if res["repo"] is None and res["description"] is None:
                continue

            msg = "Failed to update "
            if res["repo"] is not None:
                msg += " {0} ".format(res["repo"])
            if res["description"] is not None:
                msg += "because {0}".format(res["description"])

            VMN_LOGGER.warning(msg)

    if err:
        VMN_LOGGER.error(
            "Failed to update one or more " "of the required repos. See log above"
        )
        raise RuntimeError()

    return 0


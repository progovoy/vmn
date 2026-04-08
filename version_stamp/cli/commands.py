#!/usr/bin/env python3
"""Command handlers: handle_init, handle_stamp, handle_release, etc."""
import copy
import os
import random
import re
import time
from pathlib import Path

import yaml
from packaging import version as pversion

from version_stamp import version as version_mod
from version_stamp.backends.base import VMNBackend
from version_stamp.backends.factory import get_client
from version_stamp.core.constants import (
    INIT_COMMIT_MESSAGE,
    RELATIVE_TO_CURRENT_VCS_POSITION_TYPE,
    RELATIVE_TO_GLOBAL_TYPE,
    VMN_USER_NAME,
    VMN_VERSION_FORMAT,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.models import VMN_DEFAULT_CONF
from version_stamp.core.utils import WrongTagFormatException
from version_stamp.core.version_math import compare_release_modes, parse_conventional_commit_message
from version_stamp.cli.constants import (
    IGNORED_FILES,
    INIT_FILENAME,
    LOG_FILENAME,
    RepoStatus,
    VER_FILE_NAME,
    VMN_ARGS,
)
from version_stamp.cli.config_tui import handle_config  # noqa: F401

_STATUS_DESCRIPTIONS = {
    "repos_exist_locally": "all dependency repos are cloned locally",
    "deps_synced_with_conf": "dependency repos match conf.yml settings",
    "repo_tracked": "vmn tracking is initialized (.vmn/ committed)",
    "app_tracked": "app has been initialized with vmn",
    "version_not_matched": "current repo state does not match any stamped version",
    "pending": "uncommitted changes exist in the working tree",
    "detached": "HEAD is detached (not on a branch)",
    "outgoing": "local commits not yet pushed to remote",
    "dirty_deps": "dependency repos have uncommitted or unpushed changes",
}


@measure_runtime_decorator
def handle_init(vmn_ctx):
    expected_status = {"repos_exist_locally"}
    optional_status = {"deps_synced_with_conf", "version_not_matched"}

    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.debug(
            f"Error occured when getting the repo status: {status}", exc_info=True
        )

        return 1

    be = vmn_ctx.vcs.backend

    vmn_path = os.path.join(vmn_ctx.vcs.vmn_root_path, ".vmn")
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_init_path = os.path.join(vmn_path, INIT_FILENAME)
    Path(vmn_init_path).touch()
    git_ignore_path = os.path.join(vmn_path, ".gitignore")

    with open(git_ignore_path, "w+") as f:
        for ignored_file in IGNORED_FILES:
            f.write(f"{ignored_file}{os.linesep}")

    # TODO:: revert in case of failure. Use the publish_commit function
    be.commit(
        message=INIT_COMMIT_MESSAGE,
        user=VMN_USER_NAME,
        include=[vmn_init_path, git_ignore_path],
    )
    be.push()

    VMN_LOGGER.info(
        f"Initialized vmn tracking on {vmn_ctx.vcs.vmn_root_path}"
    )

    return 0


@measure_runtime_decorator
def handle_init_app(vmn_ctx):
    vmn_ctx.vcs.dry_run = vmn_ctx.args.dry
    vmn_ctx.vcs.default_release_mode = vmn_ctx.args.orm

    err = _init_app(vmn_ctx.vcs, vmn_ctx.args.version)
    if err:
        return 1

    if vmn_ctx.vcs.dry_run:
        VMN_LOGGER.info(
            "Would have initialized app tracking on {0}".format(
                vmn_ctx.vcs.root_app_dir_path
            )
        )
    else:
        VMN_LOGGER.info(
            "Initialized app tracking on {0}".format(vmn_ctx.vcs.root_app_dir_path)
        )

    return 0


@measure_runtime_decorator
def handle_stamp(vmn_ctx):
    vmn_ctx.vcs.prerelease = vmn_ctx.args.pr
    vmn_ctx.vcs.buildmetadata = None
    vmn_ctx.vcs.release_mode = vmn_ctx.args.release_mode
    vmn_ctx.vcs.optional_release_mode = vmn_ctx.args.orm
    vmn_ctx.vcs.override_root_version = vmn_ctx.args.orv
    vmn_ctx.vcs.override_version = vmn_ctx.args.ov
    vmn_ctx.vcs.dry_run = vmn_ctx.args.dry

    # For backward compatibility
    if vmn_ctx.vcs.release_mode == "micro":
        vmn_ctx.vcs.release_mode = "hotfix"

    if vmn_ctx.vcs.prerelease and vmn_ctx.vcs.prerelease[-1] == ".":
        vmn_ctx.vcs.prerelease = vmn_ctx.vcs.prerelease[:-1]

    if vmn_ctx.vcs.conventional_commits:
        if (
            vmn_ctx.vcs.release_mode is None
            and vmn_ctx.vcs.optional_release_mode is None
        ):
            max_release_mode = None
            mapping = {
                "fix": "patch",
                "feat": "minor",
                "breaking change": "major",
                "BREAKING CHANGE": "major",
                "micro": "micro",
                "perf": "",
                "refactor": "",
                "docs": "",
                "style": "",
                "test": "",
                "build": "",
                "ci": "",
                "chore": "",
                "revert": "",
                "config": "",
            }
            for m in vmn_ctx.vcs.backend.get_commits_range_iter(
                vmn_ctx.vcs.selected_tag
            ):
                try:
                    res = parse_conventional_commit_message(m)
                except ValueError:
                    continue

                if res["type"] not in mapping or mapping[res["type"]] == "":
                    continue

                if res["bc"] == "!":
                    res["type"] = "breaking change"

                if max_release_mode is None or compare_release_modes(
                    mapping[res["type"]], max_release_mode
                ):
                    max_release_mode = mapping[res["type"]]

            if vmn_ctx.vcs.default_release_mode == "optional":
                vmn_ctx.vcs.optional_release_mode = max_release_mode
            else:
                vmn_ctx.vcs.release_mode = max_release_mode

    assert vmn_ctx.vcs.release_mode is None or vmn_ctx.vcs.optional_release_mode is None

    if vmn_ctx.vcs.override_version is not None:
        try:
            props = VMNBackend.deserialize_vmn_version(
                vmn_ctx.vcs.override_version
            )
        except Exception:
            err = (
                f"Provided override {vmn_ctx.vcs.override_version} doesn't comply with: "
                f"{VMN_VERSION_FORMAT} format"
            )
            VMN_LOGGER.error(err)

            raise RuntimeError(err)

    optional_status = {"version_not_matched", "detached"}
    expected_status = {
        "repos_exist_locally",
        "repo_tracked",
        "app_tracked",
        "deps_synced_with_conf",
    }

    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        # Auto-initialize only for truly new repos/apps — check git history
        # to distinguish "never initialized" from "initialized but tags removed"
        auto_initialized = False
        be = vmn_ctx.vcs.backend
        vmn_path = os.path.join(vmn_ctx.vcs.vmn_root_path, ".vmn")
        vmn_init_file = os.path.join(vmn_path, INIT_FILENAME)

        if "repo_tracked" not in status.state and not be.is_path_tracked(vmn_init_file):
            VMN_LOGGER.info(
                "vmn tracking not initialized. Auto-initializing repository..."
            )
            ret = handle_init(vmn_ctx)
            if ret != 0:
                VMN_LOGGER.error(
                    "Auto-initialization of repository failed"
                )
                return 1
            auto_initialized = True

        if "app_tracked" not in status.state and not be.is_path_tracked(
            vmn_ctx.vcs.app_dir_path
        ):
            VMN_LOGGER.info(
                f"App '{vmn_ctx.vcs.name}' not tracked. Auto-initializing app..."
            )
            err = _init_app(vmn_ctx.vcs, "0.0.0")
            if err:
                VMN_LOGGER.error(
                    f"Auto-initialization of app '{vmn_ctx.vcs.name}' failed"
                )
                return 1
            auto_initialized = True

        if auto_initialized:
            # Refresh vcs state — auto-init created new commits/tags
            vmn_ctx.vcs.update_attrs_from_app_conf_file()
            vmn_ctx.vcs.initialize_backend_attrs()
            # Re-check status after auto-init
            status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
            if status.error:
                VMN_LOGGER.debug(
                    f"Error occurred when getting the repo status after auto-init: "
                    f"{status}",
                    exc_info=True,
                )
                return 1
        else:
            # Error was not due to missing init — original behavior
            VMN_LOGGER.debug(
                f"Error occured when getting the repo status: {status}",
                exc_info=True,
            )
            return 1

    if status.matched_version_info is not None:
        # Good we have found an existing version matching
        # the actual_deps_state
        version = status.matched_version_info["stamping"]["app"]["_version"]

        disp_version = vmn_ctx.vcs.get_be_formatted_version(version)
        VMN_LOGGER.info(
            f"Found existing version {disp_version} "
            f"and nothing has changed. Will not stamp"
        )

        return 0

    if "detached" in status.state:
        VMN_LOGGER.error("In detached head. Will not stamp new version")
        return 1

    vmn_ctx.vcs.backend.perform_cached_fetch()

    # We didn't find any existing version
    if vmn_ctx.args.pull:
        try:
            vmn_ctx.vcs.backend.perform_cached_fetch(force=True)
            vmn_ctx.vcs.retrieve_remote_changes()
        except Exception:
            VMN_LOGGER.error(
                "Failed to pull, run with --debug for more details"
            )
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

            return 1

    initial_version = _determine_initial_version(vmn_ctx)

    props = VMNBackend.deserialize_vmn_version(initial_version)
    is_from_release = props.prerelease == "release"

    # optional_release_mode should advance only in case the starting_from
    # version is release, otherwise it should be ignored
    if vmn_ctx.vcs.optional_release_mode and is_from_release:
        verstr, prerelease_count = vmn_ctx.vcs.advance_version(
            initial_version, vmn_ctx.vcs.optional_release_mode, globally=False
        )

        try:
            base_verstr = VMNBackend.get_base_vmn_version(
                verstr, hide_zero_hotfix=vmn_ctx.vcs.hide_zero_hotfix
            )
        except WrongTagFormatException as e:
            VMN_LOGGER.debug(
                f"Logged Exception message: {e}", exc_info=True
            )

            return 1

        release_tag_name = VMNBackend.serialize_vmn_tag_name(
            vmn_ctx.vcs.name, base_verstr
        )

        tag_name_prefix = f"{release_tag_name}*"
        tag = vmn_ctx.vcs.backend.get_latest_available_tag(tag_name_prefix)

        _, ver_infos = vmn_ctx.vcs.backend.get_tag_version_info(release_tag_name)
        if ver_infos:
            tag = None

        if tag is None:
            # If the version we're going towards to does not exist,
            # act as if release_mode was specified
            vmn_ctx.vcs.release_mode = vmn_ctx.vcs.optional_release_mode
        else:
            # In case some prerelease version exists, we want to
            # "start" from this version as if the release_mode was not specified
            props = VMNBackend.deserialize_vmn_version(verstr)

            initial_version = VMNBackend.serialize_vmn_version(
                base_verstr,
                prerelease=props.prerelease,
                rcn=prerelease_count[props.prerelease] - 1,
                hide_zero_hotfix=vmn_ctx.vcs.hide_zero_hotfix,
            )

    if vmn_ctx.vcs.tracked and vmn_ctx.vcs.release_mode is None:
        vmn_ctx.vcs.current_version_info["stamping"]["app"][
            "release_mode"
        ] = vmn_ctx.vcs.ver_infos_from_repo[vmn_ctx.vcs.selected_tag]["ver_info"][
            "stamping"
        ][
            "app"
        ][
            "release_mode"
        ]

    try:
        version = _stamp_version(
            vmn_ctx.vcs,
            vmn_ctx.args.pull,
            vmn_ctx.args.check_vmn_version,
            initial_version,
        )
    except Exception:
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    disp_version = vmn_ctx.vcs.get_be_formatted_version(version)
    if vmn_ctx.vcs.dry_run:
        VMN_LOGGER.info(f"Would have stamped {disp_version}")
    else:
        VMN_LOGGER.info(f"{disp_version}")

    return 0


def _determine_initial_version(vmn_ctx):
    initial_version = vmn_ctx.vcs.verstr_from_file
    base_ver = VMNBackend.get_base_vmn_version(
        initial_version,
        vmn_ctx.vcs.hide_zero_hotfix,
    )
    t = vmn_ctx.vcs.get_tag_name(base_ver)
    if t == vmn_ctx.vcs.selected_tag:
        initial_version = base_ver
    if vmn_ctx.vcs.override_version:
        initial_version = vmn_ctx.vcs.override_version
    return initial_version


def _validate_and_resolve_version(ver, status, command_name):
    """Validate buildmetadata and resolve version from status if needed.

    Returns (ver, error_code). error_code is non-zero on failure.
    """
    if ver:
        props = VMNBackend.deserialize_vmn_version(ver)
        if props.buildmetadata is not None:
            VMN_LOGGER.error(
                f"Failed to {command_name} {ver}. "
                f"Operating on metadata versions is not supported"
            )
            return ver, 1

    if ver is None and status.matched_version_info is not None:
        ver = status.matched_version_info["stamping"]["app"]["_version"]
    elif ver is None:
        VMN_LOGGER.error(
            f"When running vmn {command_name} and not on a version commit, "
            "you must specify a specific version using -v flag"
        )
        return ver, 1

    return ver, 0


def _extract_ver_info(vcs, ver):
    """Look up ver_info for a version string. Returns (tag_name, ver_infos, ver_info)."""
    tag_name, ver_infos = vcs.get_version_info_from_verstr(ver)
    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]
    return tag_name, ver_infos, ver_info


@measure_runtime_decorator
def handle_release(vmn_ctx):
    expected_status = {"repos_exist_locally", "repo_tracked", "app_tracked"}
    optional_status = {"detached", "version_not_matched", "dirty_deps", "deps_synced_with_conf"}

    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.debug(
            f"Error occured when getting the repo status: {status}", exc_info=True
        )

        return 1

    # Handle --stamp flag: must be on branch tip with a version commit (prerelease)
    if vmn_ctx.args.stamp:
        # --stamp creates a new commit + tag and pushes both,
        # so it cannot work in detached HEAD
        if "detached" in status.state:
            VMN_LOGGER.error(
                "Cannot use --stamp in detached HEAD state"
            )
            return 1

        # Deps must be clean — same requirement as regular stamp
        if status.dirty_deps:
            VMN_LOGGER.error(
                "Cannot use --stamp with dirty dependencies"
            )
            return 1

        if "deps_synced_with_conf" not in status.state:
            VMN_LOGGER.error(
                "Cannot use --stamp when dependencies are not synced with configuration"
            )
            return 1

        # N-2 scenario protection: must be on a version commit
        if status.matched_version_info is None:
            VMN_LOGGER.error(
                "Cannot use --stamp when not on a version commit. "
                "Make sure you are on the exact commit of the prerelease version."
            )
            return 1

    ver = vmn_ctx.args.version

    if ver:
        props = VMNBackend.deserialize_vmn_version(ver)
        if props.buildmetadata is not None:
            VMN_LOGGER.error(
                f"Failed to release {ver}. "
                f"Releasing metadata versions is not supported"
            )

            return 1

    if ver is None and status.matched_version_info is not None:
        # Good we have found an existing version matching
        # the actual_deps_state
        ver = status.matched_version_info["stamping"]["app"]["_version"]
    elif ver is None:
        # For --stamp, we already validated matched_version_info exists above
        VMN_LOGGER.error(
            "When running vmn release and not on a version commit, "
            "you must specify a specific version using -v flag or use --stamp"
        )

        return 1

    # Validate that we're releasing from a prerelease
    props = VMNBackend.deserialize_vmn_version(ver)
    if vmn_ctx.args.stamp and props.prerelease == "release":
        VMN_LOGGER.error(
            f"Cannot use --stamp to release {ver}. "
            f"Version must be a prerelease (e.g., 1.0.0-rc.1)"
        )
        return 1

    try:
        tag_name, ver_infos, ver_info = _extract_ver_info(vmn_ctx.vcs, ver)

        base_ver = VMNBackend.get_base_vmn_version(
            ver,
            vmn_ctx.vcs.hide_zero_hotfix,
        )

        tag_formatted_app_name = VMNBackend.serialize_vmn_tag_name(
            vmn_ctx.vcs.name,
            base_ver,
        )

        if tag_formatted_app_name in ver_infos:
            VMN_LOGGER.info(base_ver)
            return 0

        # Handle --stamp: use stamp flow for release
        if vmn_ctx.args.stamp:
            vmn_ctx.vcs.prerelease = "release"
            vmn_ctx.vcs.release_mode = None
            vmn_ctx.vcs.buildmetadata = None
            vmn_ctx.vcs.override_version = None
            vmn_ctx.vcs.override_root_version = None
            vmn_ctx.vcs.dry_run = False

            # Set extra_commit_message - required by publish_stamp
            vmn_ctx.params["extra_commit_message"] = ""

            vmn_ctx.vcs.backend.perform_cached_fetch()

            try:
                version = _stamp_version(
                    vmn_ctx.vcs,
                    pull=False,
                    check_vmn_version=False,
                    verstr=ver,
                )
            except Exception:
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
                return 1

            disp_version = vmn_ctx.vcs.get_be_formatted_version(version)
            VMN_LOGGER.info(f"{disp_version}")
            return 0

        VMN_LOGGER.info(vmn_ctx.vcs.release_app_version(tag_name, ver_info))
    except Exception:
        VMN_LOGGER.error(f"Failed to release {ver}")
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    return 0


def handle_add(vmn_ctx):
    vmn_ctx.params["buildmetadata"] = vmn_ctx.args.bm
    vmn_ctx.params["version_metadata_path"] = vmn_ctx.args.vmp
    vmn_ctx.params["version_metadata_url"] = vmn_ctx.args.vmu

    expected_status = {"repos_exist_locally", "repo_tracked", "app_tracked"}
    optional_status = {"detached", "version_not_matched", "dirty_deps", "deps_synced_with_conf"}

    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.debug(
            f"Error occured when getting the repo status: {status}", exc_info=True
        )

        return 1

    ver = vmn_ctx.args.version
    ver, err = _validate_and_resolve_version(ver, status, "add")
    if err:
        return err

    try:
        tag_name, ver_infos, ver_info = _extract_ver_info(vmn_ctx.vcs, ver)
        VMN_LOGGER.info(
            vmn_ctx.vcs.add_metadata_to_version(tag_name, ver_info)
        )
    except Exception:
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

        return 1

    return 0


@measure_runtime_decorator
def handle_show(vmn_ctx):
    if version_mod.version == "0.0.0":
        VMN_LOGGER.info("Test logprint in show")

    vmn_ctx.params["from_file"] = vmn_ctx.args.from_file

    # root app does not have raw version number
    if vmn_ctx.vcs.root_context:
        vmn_ctx.params["raw"] = False
    else:
        vmn_ctx.params["raw"] = vmn_ctx.args.raw

    vmn_ctx.params["ignore_dirty"] = vmn_ctx.args.ignore_dirty

    vmn_ctx.params["verbose"] = vmn_ctx.args.verbose
    vmn_ctx.params["conf"] = vmn_ctx.args.conf

    if vmn_ctx.args.template is not None:
        vmn_ctx.vcs.set_template(vmn_ctx.args.template)

    vmn_ctx.params["display_unique_id"] = vmn_ctx.args.display_unique_id
    vmn_ctx.params["display_type"] = vmn_ctx.args.display_type
    vmn_ctx.params["dev"] = vmn_ctx.args.dev

    if vmn_ctx.args.dev and vmn_ctx.args.from_file:
        VMN_LOGGER.error("--dev cannot be used with --from-file")
        return 1

    from version_stamp.cli.output import show

    try:
        show(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    except Exception:
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
        return 1

    return 0


@measure_runtime_decorator
def handle_gen(vmn_ctx):
    vmn_ctx.params["jinja_template"] = vmn_ctx.args.template
    vmn_ctx.params["verify_version"] = vmn_ctx.args.verify_version
    vmn_ctx.params["output"] = vmn_ctx.args.output
    vmn_ctx.params["custom_values"] = vmn_ctx.args.custom_values

    from version_stamp.cli.output import gen

    try:
        gen(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    except Exception:
        VMN_LOGGER.error("Failed to gen, run with --debug for more details")
        VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
        return 1

    return 0


@measure_runtime_decorator
def handle_goto(vmn_ctx):
    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "detached",
        "repos_exist_locally",
        "version_not_matched",
        "deps_synced_with_conf",
    }

    vmn_ctx.params["deps_only"] = vmn_ctx.args.deps_only

    status = _get_repo_status(vmn_ctx.vcs, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.debug(
            f"Error occured when getting the repo status: {status}", exc_info=True
        )

        return 1

    from version_stamp.cli.output import goto_version

    return goto_version(
        vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version, vmn_ctx.args.pull
    )


@measure_runtime_decorator
def handle_snapshot(vmn_ctx):
    from version_stamp.cli.snapshot import (
        snapshot_create,
        snapshot_list,
        snapshot_show,
        snapshot_note,
    )

    vmn_ctx.params["backend"] = vmn_ctx.args.backend
    vmn_ctx.params["bucket"] = vmn_ctx.args.bucket
    vmn_ctx.params["project"] = vmn_ctx.args.project

    action = vmn_ctx.args.action

    if action == "create":
        return snapshot_create(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.note)
    elif action == "list":
        return snapshot_list(vmn_ctx.vcs, vmn_ctx.params)
    elif action == "show":
        return snapshot_show(vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version)
    elif action == "note":
        return snapshot_note(
            vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version, vmn_ctx.args.note
        )
    else:
        VMN_LOGGER.error(f"Unknown snapshot action: {action}")
        return 1


@measure_runtime_decorator
def _get_repo_status(vcs, expected_status, optional_status=set()):
    be = vcs.backend
    default_dep_status = {
        "pending": False,
        "detached": False,
        "outgoing": False,
        "state": set(),
        "error": False,
    }
    status = RepoStatus(
        state={
            "repos_exist_locally",
            "deps_synced_with_conf",
            "repo_tracked",
            "app_tracked",
        },
    )

    vmn_path = os.path.join(vcs.vmn_root_path, ".vmn")
    vmn_init_file = os.path.join(vmn_path, INIT_FILENAME)
    if not vcs.tracked:
        status.app_tracked = False
        status.err_msgs["app_tracked"] = "Untracked app. Run vmn init-app first"
        status.state.remove("app_tracked")

        if not vcs.backend.is_path_tracked(vmn_init_file):
            status.repo_tracked = False
            status.err_msgs[
                "repo_tracked"
            ] = "vmn tracking is not yet initialized. Run vmn init on the repository"
            status.state.remove("repo_tracked")

    err = be.check_for_pending_changes()
    if err:
        status.pending = True
        status.err_msgs["pending"] = err
        status.state.add("pending")

    err = be.check_for_outgoing_changes()
    if err:
        # TODO:: Check for errcode instead of startswith
        if err.startswith("Detached head"):
            status.detached = True
            status.err_msgs["detached"] = err
            status.state.add("detached")
        else:
            # Outgoing changes cannot be in detached head
            # TODO: is it really?
            status.outgoing = True
            status.err_msgs["outgoing"] = err
            status.state.add("outgoing")

    if "name" in vcs.current_version_info["stamping"]["app"]:
        verstr = vcs.verstr_from_file
        matched_version_info = vcs.find_matching_version(verstr)
        if matched_version_info is None:
            status.version_not_matched = True
            status.state.add("version_not_matched")
        else:
            status.matched_version_info = matched_version_info

        configured_repos = set(vcs.configured_deps.keys())
        local_repos = set(vcs.actual_deps_state.keys())

        missing_deps = configured_repos - local_repos
        if missing_deps:
            paths = []
            for path in missing_deps:
                paths.append(os.path.join(vcs.vmn_root_path, path))

            status.repos_exist_locally = False
            status.err_msgs["repos_exist_locally"] = (
                f"Dependency repository were specified in conf.yml file. "
                f"However repos: {paths} do not exist. Please clone and rerun"
            )
            status.local_repos_diff = missing_deps
            status.state.remove("repos_exist_locally")

        err = 0
        common_deps = configured_repos & local_repos
        for repo in common_deps:
            # Skip local repo
            if repo == ".":
                continue

            status.repos[repo] = copy.deepcopy(default_dep_status)
            full_path = os.path.join(vcs.vmn_root_path, repo)

            dep_be, err = get_client(full_path, vcs.be_type)
            if err:
                err_str = "Failed to create backend {0}. Exiting".format(err)
                VMN_LOGGER.error(err_str)
                raise RuntimeError(err_str)

            err = dep_be.check_for_pending_changes()
            if err:
                status.dirty_deps = True
                status.err_msgs[
                    "dirty_deps"
                ] = f"{status.err_msgs['dirty_deps']}\n{err}"
                status.state.add("dirty_deps")
                status.repos[repo]["pending"] = True
                status.repos[repo]["state"].add("pending")

            if "branch" in vcs.configured_deps[repo]:
                try:
                    branch_name = dep_be.get_active_branch()
                    err_msg = (
                        f"{repo} repository is on a different branch: "
                        f"{branch_name} than what is required by the configuration: "
                        f"{vcs.configured_deps[repo]['branch']}"
                    )
                    assert branch_name == vcs.configured_deps[repo]["branch"]
                except Exception:
                    status.deps_synced_with_conf = False
                    status.err_msgs[
                        "deps_synced_with_conf"
                    ] = f"{status.err_msgs['deps_synced_with_conf']}\n{err_msg}"
                    if "deps_synced_with_conf" in status.state:
                        status.state.remove("deps_synced_with_conf")

                    status.repos[repo]["branch_synced_error"] = True
                    status.repos[repo]["state"].add("not_synced_with_conf")

            if "tag" in vcs.configured_deps[repo]:
                try:
                    err_msg = (
                        f"Repository in not on the requested tag by the configuration "
                        f"for {repo}."
                    )
                    c1 = dep_be.changeset(tag=vcs.configured_deps[repo]["tag"])
                    c2 = dep_be.changeset()
                    assert c1 == c2
                except Exception:
                    status.deps_synced_with_conf = False
                    status.err_msgs[
                        "deps_synced_with_conf"
                    ] = f"{status.err_msgs['deps_synced_with_conf']}\n{err_msg}"
                    if "deps_synced_with_conf" in status.state:
                        status.state.remove("deps_synced_with_conf")

                    status.repos[repo]["tag_synced_error"] = True
                    status.repos[repo]["state"].add("not_synced_with_conf")

            if "hash" in vcs.configured_deps[repo]:
                try:
                    err_msg = (
                        f"Repository in not on the requested hash by the configuration "
                        f"for {repo}."
                    )
                    assert vcs.configured_deps[repo]["hash"] == dep_be.changeset()
                except Exception:
                    status.deps_synced_with_conf = False
                    status.err_msgs[
                        "deps_synced_with_conf"
                    ] = f"{status.err_msgs['deps_synced_with_conf']}\n{err_msg}"
                    if "deps_synced_with_conf" in status.state:
                        status.state.remove("deps_synced_with_conf")

                    status.repos[repo]["hash_synced_error"] = True
                    status.repos[repo]["state"].add("not_synced_with_conf")

            if not dep_be.in_detached_head():
                err = dep_be.check_for_outgoing_changes()
                if err:
                    status.dirty_deps = True
                    status.err_msgs[
                        "dirty_deps"
                    ] = f"{status.err_msgs['dirty_deps']}\n{err}"
                    status.state.add("dirty_deps")
                    status.repos[repo]["outgoing"] = True
                    status.repos[repo]["state"].add("outgoing")
            else:
                status.repos[repo]["detached"] = True
                status.repos[repo]["state"].add("detached")

    if (expected_status & status.state) != expected_status:
        for msg in expected_status - status.state:
            if msg in status.err_msgs and status.err_msgs[msg]:
                VMN_LOGGER.error(status.err_msgs[msg])

        status.error = True

        return status

    unexpected = (status.state - expected_status) - optional_status
    if unexpected:
        for msg in (optional_status | status.state) - expected_status:
            if msg in status.err_msgs and status.err_msgs[msg]:
                VMN_LOGGER.error(status.err_msgs[msg])

        desc = ", ".join(
            f"{s} ({_STATUS_DESCRIPTIONS[s]})" if s in _STATUS_DESCRIPTIONS else s
            for s in sorted(unexpected)
        )
        VMN_LOGGER.error(f"Unexpected repository status: {desc}")

        status.error = True

        return status

    return status


@measure_runtime_decorator
def _init_app(versions_be_ifc, starting_version):
    optional_status = {"version_not_matched", "detached"}
    expected_status = {"repos_exist_locally", "repo_tracked", "deps_synced_with_conf"}

    status = _get_repo_status(versions_be_ifc, expected_status, optional_status)
    if status.error:
        VMN_LOGGER.debug(
            f"Error occured when getting the repo status: {status}", exc_info=True
        )

        return 1

    versions_be_ifc.create_config_files()

    info = {}
    versions_be_ifc.update_stamping_info(
        info, starting_version, starting_version, "init", {}
    )

    versions_be_ifc.backend.perform_cached_fetch()

    root_app_version = 0
    services = {}
    if versions_be_ifc.root_app_name is not None:
        tag_name, ver_infos = versions_be_ifc.get_first_reachable_version_info(
            versions_be_ifc.root_app_name,
            root_context=True,
            type=RELATIVE_TO_GLOBAL_TYPE,
        )

        versions_be_ifc.enhance_ver_info(ver_infos)

        if tag_name in ver_infos and ver_infos[tag_name]["ver_info"]:
            root_app_version = (
                int(ver_infos[tag_name]["ver_info"]["stamping"]["root_app"]["version"])
                + 1
            )
            root_app = ver_infos[tag_name]["ver_info"]["stamping"]["root_app"]
            services = copy.deepcopy(root_app["services"])

        versions_be_ifc.current_version_info["stamping"]["root_app"].update(
            {
                "version": root_app_version,
                "services": services,
            }
        )

        msg_root_app = versions_be_ifc.current_version_info["stamping"]["root_app"]
        msg_app = versions_be_ifc.current_version_info["stamping"]["app"]
        msg_root_app["services"][versions_be_ifc.name] = msg_app["_version"]

    try:
        err = versions_be_ifc.publish_stamp(starting_version, root_app_version)
    except Exception:
        VMN_LOGGER.debug("Logged Exception message: ", exc_info=True)
        versions_be_ifc.backend.revert_local_changes(versions_be_ifc.version_files)
        err = -1

    if err:
        VMN_LOGGER.error("Failed to init app")
        raise RuntimeError()

    return 0


@measure_runtime_decorator
def _stamp_version(versions_be_ifc, pull, check_vmn_version, verstr):
    stamped = False
    retries = 3
    override_verstr = verstr

    override_main_current_version = versions_be_ifc.override_root_version

    if check_vmn_version:
        newer_stamping = version_mod.version != "0.0.0" and (
            pversion.parse(
                versions_be_ifc.current_version_info["vmn_info"]["vmn_version"]
            )
            > pversion.parse(version_mod.version)
        )

        if newer_stamping:
            VMN_LOGGER.error(
                "Refusing to stamp with old vmn. Please upgrade"
            )
            raise RuntimeError()

    if versions_be_ifc.template_err_str:
        VMN_LOGGER.warning(versions_be_ifc.template_err_str)

    while retries:
        retries -= 1

        current_version = versions_be_ifc.stamp_app_version(override_verstr)
        main_ver = versions_be_ifc.stamp_root_app_version(override_main_current_version)

        try:
            err = versions_be_ifc.publish_stamp(current_version, main_ver)
        except Exception as exc:
            VMN_LOGGER.error(
                f"Failed to publish. Will revert local changes {exc}\nFor more details use --debug"
            )
            VMN_LOGGER.debug("Exception info: ", exc_info=True)
            versions_be_ifc.backend.revert_local_changes(versions_be_ifc.version_files)
            err = -1

        if not err:
            stamped = True
            break

        if err == 1:
            override_verstr = current_version

            override_main_current_version = main_ver

            VMN_LOGGER.warning(
                "Failed to publish. Will try to auto-increase "
                "from {0} to {1}".format(
                    current_version,
                    versions_be_ifc.gen_advanced_version(override_verstr)[0],
                )
            )
        elif err == 2:
            if not pull:
                break

            time.sleep(random.randint(1, 5))
            try:
                versions_be_ifc.retrieve_remote_changes()
            except Exception:
                VMN_LOGGER.error("Failed to pull", exc_info=True)
        else:
            break

    if not stamped:
        err = "Failed to stamp"
        VMN_LOGGER.error(err)
        raise RuntimeError(err)

    return current_version


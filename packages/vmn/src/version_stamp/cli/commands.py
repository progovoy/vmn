#!/usr/bin/env python3
"""Command handlers: handle_init, handle_stamp, handle_release, etc."""
import os
import random
import time

from packaging import version as pversion

from version_stamp import version as version_mod
from version_stamp.cli.config_tui import handle_config  # noqa: F401
from version_stamp.compat.release_mode import normalize_release_mode
from version_stamp.core.changelog import release_mode_for_commit
from version_stamp.core.constants import VMN_VERSION_FORMAT
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import WrongTagFormatException
from version_stamp.core.version_math import (
    compare_release_modes,
    deserialize_vmn_version,
    get_base_vmn_version,
    parse_conventional_commit_message,
    serialize_vmn_version,
)
from version_stamp.stamping.init import (
    _init_app,
    auto_init_if_needed,
    init_repo,
)
from version_stamp.stamping.repo_status import (
    READ_ONLY_EXPECTED,
    READ_ONLY_OPTIONAL,
    _get_repo_status,
    _log_status_error,
    _status_or_fail,
)

# The repo status `vmn release` and `vmn add` demand, and what they tolerate.
_VERSION_OP_EXPECTED = frozenset({"repos_exist_locally", "repo_tracked", "app_tracked"})
_VERSION_OP_OPTIONAL = frozenset(
    {"detached", "version_not_matched", "dirty_deps", "deps_synced_with_conf"}
)


@measure_runtime_decorator
def handle_init(vmn_ctx, extra_optional=None):
    return init_repo(vmn_ctx.vcs, extra_optional)


@measure_runtime_decorator
def handle_init_app(vmn_ctx):
    vmn_ctx.vcs.dry_run = vmn_ctx.args.dry
    vmn_ctx.vcs.release_mode_policy = vmn_ctx.args.orm

    err = _init_app(vmn_ctx.vcs, vmn_ctx.args.version)
    if err:
        return 1

    if vmn_ctx.vcs.dry_run:
        VMN_LOGGER.info(
            f"Would have initialized app tracking on {vmn_ctx.vcs.root_app_dir_path}"
        )
    else:
        VMN_LOGGER.info(
            f"Initialized app tracking on {vmn_ctx.vcs.root_app_dir_path}"
        )

    return 0


def _describe_release_mode_policy(policy):
    if policy == "optional":
        return "applied as an optional release mode (--orm behavior)"

    return "applied as a strict release mode (-r behavior)"


def _is_root_version(verstr):
    """A bare root-app integer, which ``--ov`` can't stamp (that is ``--orv``)."""
    if verstr is None:
        return False
    return "root" in deserialize_vmn_version(verstr).types


def _log_cli_release_mode(vcs):
    if vcs.release_mode is not None:
        flag, mode = "-r/--release-mode", vcs.release_mode
    else:
        flag, mode = "--orm/--optional-release-mode", vcs.optional_release_mode

    VMN_LOGGER.debug(
        f"Release mode '{mode}' chosen because it was given on the command line "
        f"via {flag}. Conventional commits and default_release_mode are not "
        f"consulted when a release mode is passed explicitly."
    )


def _log_conventional_commits_release_mode(vcs, release_mode, trigger):
    if release_mode is None:
        VMN_LOGGER.debug(
            f"No release mode chosen from conventional commits: no commit since "
            f"{vcs.selected_tag} mapped to a release mode."
        )
        return

    VMN_LOGGER.debug(
        f"Release mode '{release_mode}' chosen because conventional commit "
        f'"{trigger}" maps to it, and it is the highest release mode among the '
        f"commits since {vcs.selected_tag}. It is "
        f"{_describe_release_mode_policy(vcs.release_mode_policy)}, per "
        f"release_mode_policy={vcs.release_mode_policy}."
    )


def _log_default_release_mode(vcs):
    VMN_LOGGER.debug(
        f"Release mode '{vcs.default_release_mode}' chosen because it is the "
        f"configured default_release_mode, and nothing earlier resolved a mode. "
        f"It is {_describe_release_mode_policy(vcs.release_mode_policy)}, per "
        f"release_mode_policy={vcs.release_mode_policy}."
    )


def _log_no_release_mode(vcs):
    VMN_LOGGER.debug(
        f"No release mode chosen: none was given on the command line, "
        f"conventional_commits is {bool(vcs.conventional_commits)} and "
        f"default_release_mode is not configured."
    )


def _apply_push_credentials(vmn_ctx):
    push_user = vmn_ctx.args.git_push_user or os.environ.get("VMN_GIT_PUSH_USER")
    push_token = vmn_ctx.args.git_push_token or os.environ.get("VMN_GIT_PUSH_TOKEN")
    if push_user and push_token:
        vmn_ctx.vcs.backend.set_push_credentials(push_user, push_token)
    elif bool(push_user) != bool(push_token):
        VMN_LOGGER.warning(
            "Both --git-push-user and --git-push-token must be provided together. "
            "Ignoring partial credentials."
        )


@measure_runtime_decorator
def handle_stamp(vmn_ctx):
    vmn_ctx.vcs.prerelease = vmn_ctx.args.pr
    vmn_ctx.vcs.buildmetadata = None
    vmn_ctx.vcs.release_mode = vmn_ctx.args.release_mode
    vmn_ctx.vcs.optional_release_mode = vmn_ctx.args.orm
    vmn_ctx.vcs.override_root_version = vmn_ctx.args.orv
    vmn_ctx.vcs.override_version = vmn_ctx.args.ov
    vmn_ctx.vcs.dry_run = vmn_ctx.args.dry

    _apply_push_credentials(vmn_ctx)

    vmn_ctx.vcs.release_mode = normalize_release_mode(vmn_ctx.vcs.release_mode)

    if vmn_ctx.vcs.prerelease and vmn_ctx.vcs.prerelease[-1] == ".":
        vmn_ctx.vcs.prerelease = vmn_ctx.vcs.prerelease[:-1]

    if (
        vmn_ctx.vcs.release_mode is not None
        or vmn_ctx.vcs.optional_release_mode is not None
    ):
        _log_cli_release_mode(vmn_ctx.vcs)

    if vmn_ctx.vcs.conventional_commits:
        if (
            vmn_ctx.vcs.release_mode is None
            and vmn_ctx.vcs.optional_release_mode is None
        ):
            max_release_mode = None
            max_release_trigger = None
            for m in vmn_ctx.vcs.backend.get_commits_range_iter(
                vmn_ctx.vcs.selected_tag
            ):
                try:
                    res = parse_conventional_commit_message(m)
                except ValueError:
                    continue

                mode = release_mode_for_commit(res)
                if mode is None:
                    continue

                if max_release_mode is None or compare_release_modes(
                    mode, max_release_mode
                ):
                    max_release_mode = mode
                    max_release_trigger = f"{res['type']}: {res['description']}"

            _log_conventional_commits_release_mode(
                vmn_ctx.vcs, max_release_mode, max_release_trigger
            )

            if vmn_ctx.vcs.release_mode_policy == "optional":
                vmn_ctx.vcs.optional_release_mode = max_release_mode
            else:
                vmn_ctx.vcs.release_mode = max_release_mode

    if vmn_ctx.vcs.release_mode is None and vmn_ctx.vcs.optional_release_mode is None:
        if vmn_ctx.vcs.default_release_mode:
            _log_default_release_mode(vmn_ctx.vcs)

            if vmn_ctx.vcs.release_mode_policy == "optional":
                vmn_ctx.vcs.optional_release_mode = vmn_ctx.vcs.default_release_mode
            else:
                vmn_ctx.vcs.release_mode = vmn_ctx.vcs.default_release_mode
        else:
            _log_no_release_mode(vmn_ctx.vcs)

    assert vmn_ctx.vcs.release_mode is None or vmn_ctx.vcs.optional_release_mode is None

    if _is_root_version(vmn_ctx.vcs.override_version):
        VMN_LOGGER.error(
            f"Version must be in format: {VMN_VERSION_FORMAT}. "
            f"Use --orv to override a root app version"
        )
        return 1

    optional_status = {"version_not_matched", "detached"}
    expected_status = {
        "repos_exist_locally",
        "repo_tracked",
        "app_tracked",
        "deps_synced_with_conf",
    }

    status = _get_repo_status(
        vmn_ctx.vcs,
        expected_status,
        optional_status,
        suppress_errors={"repo_tracked", "app_tracked"},
    )
    if status.error:
        # Auto-initialize only for truly new repos/apps — check git history
        # to distinguish "never initialized" from "initialized but tags removed"
        err, initialized = auto_init_if_needed(vmn_ctx.vcs)
        if err:
            return 1
        if not initialized:
            _log_status_error(status)
            return 1
        status = _status_or_fail(vmn_ctx.vcs, expected_status, optional_status)
        if status is None:
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
            _retrieve_stamp_updates(vmn_ctx.vcs)
        except Exception:
            VMN_LOGGER.error("Failed to pull, run with --debug for more details")
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

            return 1

    initial_version = _determine_initial_version(vmn_ctx)

    props = deserialize_vmn_version(initial_version)
    is_from_release = props.prerelease == "release"

    # optional_release_mode should advance only in case the starting_from
    # version is release, otherwise it should be ignored
    if vmn_ctx.vcs.optional_release_mode and is_from_release:
        verstr, prerelease_count = vmn_ctx.vcs.advance_version(
            initial_version, vmn_ctx.vcs.optional_release_mode, globally=False
        )

        try:
            base_verstr = get_base_vmn_version(
                verstr, hide_zero_hotfix=vmn_ctx.vcs.hide_zero_hotfix
            )
        except WrongTagFormatException as e:
            VMN_LOGGER.debug(f"Logged Exception message: {e}", exc_info=True)

            return 1

        release_tag_name = vmn_ctx.vcs.get_tag_name(base_verstr)

        tag_name_prefix = f"{release_tag_name}*"
        tag = vmn_ctx.vcs.backend.get_latest_available_tag(tag_name_prefix)

        _, ver_infos = vmn_ctx.vcs.release_tag_info(verstr)
        if ver_infos:
            tag = None

        if tag is None:
            # If the version we're going towards to does not exist,
            # act as if release_mode was specified
            vmn_ctx.vcs.release_mode = vmn_ctx.vcs.optional_release_mode
        else:
            # In case some prerelease version exists, we want to
            # "start" from this version as if the release_mode was not specified
            props = deserialize_vmn_version(verstr)

            initial_version = serialize_vmn_version(
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


def _retrieve_stamp_updates(vcs):
    vcs.backend.perform_cached_fetch(force=True)
    vcs.retrieve_remote_changes()


def _determine_initial_version(vmn_ctx):
    initial_version = vmn_ctx.vcs.verstr_from_file
    base_ver = get_base_vmn_version(
        initial_version,
        vmn_ctx.vcs.hide_zero_hotfix,
    )
    t = vmn_ctx.vcs.get_tag_name(base_ver)
    if t == vmn_ctx.vcs.selected_tag:
        initial_version = base_ver
    if vmn_ctx.vcs.override_version:
        initial_version = vmn_ctx.vcs.override_version
    return initial_version


def _validate_and_resolve_version(ver, status, command_name, hint=""):
    """Validate buildmetadata and resolve version from status if needed.

    Returns (ver, error_code). error_code is non-zero on failure. *hint* is
    appended to the "specify a version" error.
    """
    if ver:
        props = deserialize_vmn_version(ver)
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
            f"you must specify a specific version using -v flag{hint}"
        )
        return ver, 1

    return ver, 0


def _extract_ver_info(vcs, ver):
    """Look up ver_info for a version string (None: the selected version).

    Returns (tag_name, ver_infos, ver_info).
    """
    if ver is None:
        tag_name, ver_infos = vcs.selected_tag, vcs.ver_infos_from_repo
    else:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(ver)
    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        ver_info = None
    else:
        ver_info = ver_infos[tag_name]["ver_info"]
    return tag_name, ver_infos, ver_info


@measure_runtime_decorator
def handle_release(vmn_ctx):
    _apply_push_credentials(vmn_ctx)

    status = _status_or_fail(
        vmn_ctx.vcs, _VERSION_OP_EXPECTED, _VERSION_OP_OPTIONAL
    )
    if status is None:
        return 1

    # Handle --stamp flag: must be on branch tip with a version commit (prerelease)
    if vmn_ctx.args.stamp:
        # --stamp creates a new commit + tag and pushes both,
        # so it cannot work in detached HEAD
        if "detached" in status.state:
            VMN_LOGGER.error("Cannot use --stamp in detached HEAD state")
            return 1

        # Deps must be clean — same requirement as regular stamp
        if status.dirty_deps:
            VMN_LOGGER.error("Cannot use --stamp with dirty dependencies")
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

    ver, err = _validate_and_resolve_version(
        vmn_ctx.args.version, status, "release", hint=" or use --stamp"
    )
    if err:
        return err

    # Validate that we're releasing from a prerelease
    props = deserialize_vmn_version(ver)
    if vmn_ctx.args.stamp and props.prerelease == "release":
        VMN_LOGGER.error(
            f"Cannot use --stamp to release {ver}. "
            f"Version must be a prerelease (e.g., 1.0.0-rc.1)"
        )
        return 1

    try:
        tag_name, ver_infos, ver_info = _extract_ver_info(vmn_ctx.vcs, ver)

        base_ver = get_base_vmn_version(
            ver,
            vmn_ctx.vcs.hide_zero_hotfix,
        )

        tag_formatted_app_name = vmn_ctx.vcs.get_tag_name(base_ver)

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

    status = _status_or_fail(
        vmn_ctx.vcs, _VERSION_OP_EXPECTED, _VERSION_OP_OPTIONAL
    )
    if status is None:
        return 1

    ver = vmn_ctx.args.version
    ver, err = _validate_and_resolve_version(ver, status, "add")
    if err:
        return err

    try:
        tag_name, ver_infos, ver_info = _extract_ver_info(vmn_ctx.vcs, ver)
        VMN_LOGGER.info(vmn_ctx.vcs.add_metadata_to_version(tag_name, ver_info))
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
    expected_status = READ_ONLY_EXPECTED
    optional_status = {
        "detached",
        "repos_exist_locally",
        "version_not_matched",
        "deps_synced_with_conf",
    }

    # Restoring a dev version snapshots (and thus preserves) any dirty work via
    # the safety net, so a dirty tree is not an error for a dev-version goto.
    from version_stamp.core.version_math import is_dev_version

    if vmn_ctx.args.version and is_dev_version(vmn_ctx.args.version):
        optional_status = READ_ONLY_OPTIONAL

    vmn_ctx.params["deps_only"] = vmn_ctx.args.deps_only
    vmn_ctx.params["force"] = vmn_ctx.args.force

    if _status_or_fail(vmn_ctx.vcs, expected_status, optional_status) is None:
        return 1

    from version_stamp.cli.output import goto_version

    return goto_version(
        vmn_ctx.vcs, vmn_ctx.params, vmn_ctx.args.version, vmn_ctx.args.pull
    )


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
            VMN_LOGGER.error("Refusing to stamp with old vmn. Please upgrade")
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
            err = -1

        if not err:
            stamped = True
            break

        if err == 1:
            override_verstr = current_version

            override_main_current_version = main_ver

            next_verstr, _ = versions_be_ifc.advance_version(
                override_verstr, versions_be_ifc.release_mode
            )
            VMN_LOGGER.warning(
                "Failed to publish. Will try to auto-increase "
                f"from {current_version} to {next_verstr}"
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

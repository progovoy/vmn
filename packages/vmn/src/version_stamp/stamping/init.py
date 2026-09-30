#!/usr/bin/env python3
"""`vmn init`, `vmn init-app`, and auto-init of an untracked repo or app."""
import os
from pathlib import Path

from version_stamp.cli.constants import IGNORED_FILES, INIT_FILENAME
from version_stamp.core.constants import (
    INIT_COMMIT_MESSAGE,
    RELATIVE_TO_GLOBAL_TYPE,
    VER_FILE_NAME,
    VMN_USER_NAME,
)
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.stamping.repo_status import _status_or_fail, repo_initialized


def _add_ignored_files(git_ignore_path):
    """Append vmn's ignore entries missing from *git_ignore_path*, keeping
    whatever the user put there."""
    existing = ""
    if os.path.exists(git_ignore_path):
        with open(git_ignore_path) as f:
            existing = f.read()
    present = set(existing.splitlines())
    missing = [entry for entry in IGNORED_FILES if entry not in present]
    if existing and not existing.endswith("\n"):
        existing += "\n"
    with open(git_ignore_path, "w") as f:
        f.write(existing + "".join(f"{entry}\n" for entry in missing))


def app_initialized(be, app_dir_path):
    """`vmn init-app` ran for the app: its version file is committed (a
    committed conf.yml alone does not make an initialized app)."""
    return be.is_path_tracked(os.path.join(app_dir_path, VER_FILE_NAME))


def _revert_failed_publish(versions_be_ifc):
    """Restore the tracked version files and drop an untracked version file
    (a failed first init-app writes it; left behind, it would sit in the tree)."""
    be = versions_be_ifc.backend
    files = versions_be_ifc.version_files
    be.revert_local_changes([f for f in files if be.is_path_tracked(f)])
    version_file = versions_be_ifc.version_file_path
    if os.path.exists(version_file) and not be.is_path_tracked(version_file):
        os.remove(version_file)


@measure_runtime_decorator
def init_repo(vcs, extra_optional=None):
    """Commit vmn's .vmn/conf.yml and .vmn/.gitignore and push them."""
    optional_status = {"deps_synced_with_conf", "version_not_matched"}
    if extra_optional:
        optional_status |= extra_optional

    if _status_or_fail(vcs, {"repos_exist_locally"}, optional_status) is None:
        return 1

    be = vcs.backend

    vmn_path = os.path.join(vcs.vmn_root_path, ".vmn")
    Path(vmn_path).mkdir(parents=True, exist_ok=True)
    vmn_init_path = os.path.join(vmn_path, INIT_FILENAME)
    Path(vmn_init_path).touch()
    git_ignore_path = os.path.join(vmn_path, ".gitignore")
    _add_ignored_files(git_ignore_path)

    # TODO:: revert in case of failure. Use the publish_commit function
    be.commit(
        message=INIT_COMMIT_MESSAGE,
        user=VMN_USER_NAME,
        include=[vmn_init_path, git_ignore_path],
    )
    be.push()

    VMN_LOGGER.info(f"Initialized vmn tracking on {vcs.vmn_root_path}")

    return 0


@measure_runtime_decorator
def _init_app(versions_be_ifc, starting_version, extra_optional=None):
    optional_status = {"version_not_matched", "detached"}
    if extra_optional:
        optional_status |= extra_optional
    expected_status = {"repos_exist_locally", "repo_tracked", "deps_synced_with_conf"}

    if _status_or_fail(versions_be_ifc, expected_status, optional_status) is None:
        return 1

    versions_be_ifc.create_config_files()

    info = {}
    versions_be_ifc.update_stamping_info(
        info, starting_version, starting_version, "init", {}
    )

    versions_be_ifc.backend.perform_cached_fetch()

    root_app_version = 0
    if versions_be_ifc.root_app_name is not None:
        root_app_version, services = versions_be_ifc._next_root_state(
            RELATIVE_TO_GLOBAL_TYPE, allow_missing=True
        )
        versions_be_ifc.current_version_info["stamping"]["root_app"].update(
            {"version": root_app_version, "services": services}
        )

    try:
        err = versions_be_ifc.publish_stamp(starting_version, root_app_version)
    except Exception:
        VMN_LOGGER.debug("Logged Exception message: ", exc_info=True)
        _revert_failed_publish(versions_be_ifc)
        err = -1

    if err:
        VMN_LOGGER.error("Failed to init app")
        return 1

    return 0


def auto_init_if_needed(vcs, extra_optional=None):
    """Initialize the repo and/or the app when vmn has never tracked them.

    Returns ``(err, initialized)``: *err* is 1 when an init failed; the vcs is
    refreshed when *initialized*. Only a truly new repo/app is initialized —
    one whose tags were removed still has its committed files.
    """
    repo_missing, app_missing = init_needed(vcs)

    if repo_missing:
        VMN_LOGGER.info("vmn tracking not initialized. Auto-initializing repository...")
        if init_repo(vcs, extra_optional):
            VMN_LOGGER.error("Auto-initialization of repository failed")
            return 1, False

    if app_missing:
        # Name the app and the baseline: a typo'd app name becomes a permanent
        # git tag, so creating one must never be silent.
        VMN_LOGGER.info(f"Auto-initializing new vmn app '{vcs.name}' at 0.0.0...")
        if _init_app(vcs, "0.0.0", extra_optional):
            VMN_LOGGER.error(f"Auto-initialization of app '{vcs.name}' failed")
            return 1, False

    initialized = repo_missing or app_missing
    if initialized:
        vcs.update_attrs_from_app_conf_file()
        vcs.initialize_backend_attrs()
    return 0, initialized


def init_needed(vcs):
    """``(repo_missing, app_missing)``: what vmn has never initialized."""
    if vcs.tracked:
        return False, False
    be = vcs.backend
    return (
        not repo_initialized(be, vcs.vmn_root_path),
        not app_initialized(be, vcs.app_dir_path),
    )

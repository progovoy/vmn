#!/usr/bin/env python3
"""The repo status vmn commands check before acting: tracking, dirtiness, deps."""
import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from version_stamp.backends.factory import get_client
from version_stamp.cli.constants import INIT_FILENAME
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.stamping.dep_pins import (
    _DEP_PIN_CHECKS,
    _dep_pin_error,
    _mark_unsynced,
)

# The status read-only commands (show, gen, snapshot, experiments) demand of
# the repo, and every other state they tolerate.
READ_ONLY_EXPECTED = frozenset({"repo_tracked", "app_tracked"})
READ_ONLY_OPTIONAL = frozenset(
    {
        "repos_exist_locally",
        "detached",
        "pending",
        "outgoing",
        "version_not_matched",
        "dirty_deps",
        "deps_synced_with_conf",
    }
)

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


@dataclass
class RepoStatus:
    pending: bool = False
    detached: bool = False
    outgoing: bool = False
    state: Set[str] = field(default_factory=set)
    error: bool = False
    repos_exist_locally: bool = True
    deps_synced_with_conf: bool = True
    repo_tracked: bool = True
    app_tracked: bool = True
    version_not_matched: bool = False
    dirty_deps: bool = False
    err_msgs: Dict[str, str] = field(
        default_factory=lambda: {
            "dirty_deps": "",
            "deps_synced_with_conf": "",
            "repo_tracked": "vmn repo tracking is already initialized",
            "app_tracked": "vmn app tracking is already initialized",
        }
    )
    repos: Dict[str, Any] = field(default_factory=dict)
    matched_version_info: Optional[dict] = None
    local_repos_diff: Set[str] = field(default_factory=set)


def repo_initialized(be, vmn_root_path):
    """`vmn init` ran here: its conf.yml or .gitignore is committed (repos
    initialized before the conf.yml existed have only the .gitignore)."""
    vmn_path = os.path.join(vmn_root_path, ".vmn")
    return any(
        be.is_path_tracked(os.path.join(vmn_path, name))
        for name in (INIT_FILENAME, ".gitignore")
    )


def _status_or_fail(vcs, expected_status, optional_status=frozenset(), **kwargs):
    """The repo status, or None (logged) when it does not meet the expectations."""
    status = _get_repo_status(vcs, expected_status, optional_status, **kwargs)
    if status.error:
        _log_status_error(status)
        return None
    return status


def _log_status_error(status):
    VMN_LOGGER.debug(
        f"Error occured when getting the repo status: {status}", exc_info=True
    )


def get_dirty_states(optional_status, status):
    dirty_states = (status.state & optional_status) - {
        "detached",
        "repos_exist_locally",
        "deps_synced_with_conf",
    }

    try:
        debug_msg = ""
        for k in status.err_msgs.keys():
            if k in dirty_states:
                debug_msg = f"{debug_msg}\n{status.err_msgs[k]}"

        if debug_msg:
            VMN_LOGGER.debug(f"Debug for dirty states call:{debug_msg}")
    except Exception:
        VMN_LOGGER.debug("Logged Exception message: ", exc_info=True)

    return dirty_states


@measure_runtime_decorator
def _get_repo_status(
    vcs, expected_status, optional_status=set(), suppress_errors=frozenset()
):
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

    if not vcs.tracked:
        status.app_tracked = False
        status.err_msgs["app_tracked"] = "Untracked app. Run vmn init-app first"
        status.state.remove("app_tracked")

        if not repo_initialized(vcs.backend, vcs.vmn_root_path):
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
                err_str = f"Failed to create backend {err}. Exiting"
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

            for pin in _DEP_PIN_CHECKS:
                if pin not in vcs.configured_deps[repo]:
                    continue
                err_msg = _dep_pin_error(
                    pin, repo, full_path, dep_be, vcs.configured_deps[repo][pin]
                )
                if err_msg:
                    _mark_unsynced(status, repo, pin, err_msg)

            if not dep_be.in_detached_head():
                err = dep_be.check_for_outgoing_changes()
                if err:
                    status.repos[repo]["outgoing"] = True
                    status.repos[repo]["state"].add("outgoing")
                    if "outgoing" not in optional_status:
                        status.dirty_deps = True
                        status.err_msgs[
                            "dirty_deps"
                        ] = f"{status.err_msgs['dirty_deps']}\n{err}"
                        status.state.add("dirty_deps")
            else:
                status.repos[repo]["detached"] = True
                status.repos[repo]["state"].add("detached")

    if (expected_status & status.state) != expected_status:
        for msg in expected_status - status.state:
            if msg in suppress_errors:
                continue
            if status.err_msgs.get(msg):
                VMN_LOGGER.error(status.err_msgs[msg])

        status.error = True

        return status

    unexpected = (status.state - expected_status) - optional_status
    if unexpected:
        for msg in unexpected:
            if status.err_msgs.get(msg):
                VMN_LOGGER.error(status.err_msgs[msg])

        desc = ", ".join(
            f"{s} ({_STATUS_DESCRIPTIONS[s]})" if s in _STATUS_DESCRIPTIONS else s
            for s in sorted(unexpected)
        )
        VMN_LOGGER.error(f"Unexpected repository status: {desc}")

        if "pending" in unexpected:
            VMN_LOGGER.info(
                "Hint: commit or stash your changes first, or use "
                f"'vmn snapshot create {vcs.name}' to save your work."
            )

        status.error = True

        return status

    return status

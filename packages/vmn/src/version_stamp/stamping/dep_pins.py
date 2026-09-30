#!/usr/bin/env python3
"""Whether a dependency repo sits on the branch/tag/hash its conf pins."""
from version_stamp.core.logging import VMN_LOGGER


def _on_configured_branch(dep_be, branch_name, configured_branch, outgoing):
    """A dep is on its configured branch, or on a local branch that tracks it
    and has no commits of its own (so the recorded hash is reachable).

    The second case is a `vmn wt` island's private branch. ``outgoing`` is the
    dep's (memoized) check_for_outgoing_changes.
    """
    if branch_name == configured_branch:
        return True
    tracked = (dep_be.remote_active_branch or "").split("/", 1)[-1]
    return tracked == configured_branch and outgoing() is None


def _branch_pin_error(repo, dep_be, branch, outgoing):
    branch_name = dep_be.get_active_branch()
    if _on_configured_branch(dep_be, branch_name, branch, outgoing):
        return None
    return (
        f"{repo} repository is on a different branch: "
        f"{branch_name} than what is required by the configuration: {branch}"
    )


def _tag_pin_error(repo, dep_be, tag):
    if dep_be.changeset(tag=tag) == dep_be.changeset():
        return None
    return f"Repository in not on the requested tag by the configuration for {repo}."


def _hash_pin_error(repo, dep_be, changeset):
    if changeset == dep_be.changeset():
        return None
    return f"Repository in not on the requested hash by the configuration for {repo}."


_DEP_PIN_CHECKS = {
    "branch": _branch_pin_error,
    "tag": _tag_pin_error,
    "hash": _hash_pin_error,
}


def _dep_pin_error(pin, repo, dep_be, value, outgoing):
    """Why dep ``repo`` is off its configured ``pin`` (branch/tag/hash), or None."""
    extra = (outgoing,) if pin == "branch" else ()
    try:
        return _DEP_PIN_CHECKS[pin](repo, dep_be, value, *extra)
    except Exception:
        VMN_LOGGER.debug(f"Failed to check the {pin} of {repo}", exc_info=True)
        return (
            f"Failed to verify that {repo} repository is on the {pin}: {value} "
            f"required by the configuration"
        )


def _mark_unsynced(status, repo, pin, err_msg):
    status.deps_synced_with_conf = False
    status.err_msgs[
        "deps_synced_with_conf"
    ] = f"{status.err_msgs['deps_synced_with_conf']}\n{err_msg}"
    status.state.discard("deps_synced_with_conf")
    status.repos[repo][f"{pin}_synced_error"] = True
    status.repos[repo]["state"].add("not_synced_with_conf")

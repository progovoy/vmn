"""Version and dependency resolution for worktree islands."""
import os

from version_stamp.cli.worktree_git import git_current_branch
from version_stamp.core.constants import VMN_READONLY_REMOTE
from version_stamp.core.logging import VMN_LOGGER


def resolve_version_source(vmn_ctx, source):
    if source["type"] != "version":
        return True
    resolved = version_app_data(vmn_ctx, source["ref"])
    if resolved is None:
        VMN_LOGGER.error(f"Version {source['ref']} of {vmn_ctx.vcs.name} was not found")
        return False

    tag_name, _ = resolved
    commit = vmn_ctx.vcs.backend.changeset(tag_name)
    if not commit:
        VMN_LOGGER.error(f"Failed to resolve commit for version {source['ref']}")
        return False
    source["tag"] = tag_name
    source["commit"] = commit
    return True


def resolve_deps(vmn_ctx, source):
    if source["type"] == "version":
        return deps_from_version(vmn_ctx, source["ref"])
    return deps_from_configured(vmn_ctx)


def deps_from_version(vmn_ctx, version):
    resolved = version_app_data(vmn_ctx, version)
    if resolved is None:
        return None
    _, app_data = resolved
    changesets = app_data.get("changesets", {})
    return _collect_deps(
        {rel: _version_dep_info(rel, raw) for rel, raw in changesets.items()}
    )


def deps_from_configured(vmn_ctx):
    vcs = vmn_ctx.vcs
    configured = getattr(vcs, "configured_deps", {})
    actual = getattr(vcs, "actual_deps_state", {})
    root = getattr(vcs, "vmn_root_path", None)
    raw_deps = {}
    for rel_path, conf in configured.items():
        if rel_path == ".":
            continue
        local = os.path.join(root, rel_path) if root else None
        raw_deps[rel_path] = _configured_dep_info(
            rel_path, conf, actual.get(rel_path, {}), local
        )
    return _collect_deps(raw_deps)


def _local_branch(path):
    return git_current_branch(path) if path and os.path.isdir(path) else None


def _configured_dep_info(rel_path, conf, actual_info, local_path):
    """Where an island should start a dependency, given its conf pin.

    A hash or tag pin wins. A branch pin keeps the local checkout when it is
    already on that branch (so the island starts at the current hash) and
    otherwise asks for the branch to be fetched. With no pin the island follows
    the local checkout.
    """
    local_hash = actual_info.get("hash")
    info = {
        "remote": conf.get("remote") or actual_info.get("remote"),
        "branch": conf.get("branch"),
        "rel_path": rel_path,
        "source_branch": None,
        "fetch": False,
    }
    if conf.get("hash"):
        info.update(hash=conf["hash"], start_point=conf["hash"])
    elif conf.get("tag"):
        info.update(hash=None, start_point=conf["tag"])
    elif conf.get("branch"):
        branch = conf["branch"]
        info["source_branch"] = branch
        if _local_branch(local_path) == branch:
            info.update(hash=local_hash, start_point=local_hash)
        else:
            info.update(
                hash=None,
                start_point=f"{VMN_READONLY_REMOTE}/{branch}",
                fetch=True,
            )
    else:
        info.update(
            hash=local_hash,
            start_point=local_hash,
            source_branch=_local_branch(local_path),
        )
    return info


def _version_dep_info(rel_path, raw_info):
    """A dep of a --from-version island: detached at its recorded hash."""
    return {
        "hash": raw_info.get("hash"),
        "start_point": raw_info.get("hash"),
        "remote": raw_info.get("remote"),
        "branch": raw_info.get("branch"),
        "rel_path": rel_path,
        "source_branch": None,
        "fetch": False,
    }


def _collect_deps(raw_deps):
    deps = {}
    for rel_path, raw_info in raw_deps.items():
        if rel_path == ".":
            continue
        dep_name = os.path.basename(rel_path.rstrip("/"))
        if dep_name in deps:
            VMN_LOGGER.error(
                f"Dependencies '{deps[dep_name]['rel_path']}' and '{rel_path}' "
                f"both map to island directory '{dep_name}'"
            )
            return None
        info = dict(raw_info)
        deps[dep_name] = info
    return deps


def version_app_data(vmn_ctx, version):
    try:
        tag_name, ver_infos = vmn_ctx.vcs.get_version_info_from_verstr(version)
        if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
            return None
        app_data = ver_infos[tag_name]["ver_info"]["stamping"]["app"]
        return tag_name, app_data
    except Exception:
        VMN_LOGGER.debug("Failed to resolve worktree version", exc_info=True)
        return None


def find_dep_repo_path(vmn_ctx, dep_info):
    rel_path = dep_info.get("rel_path")
    if not rel_path:
        return None
    full_path = os.path.join(vmn_ctx.vcs.vmn_root_path, rel_path)
    if os.path.isdir(full_path):
        return os.path.realpath(full_path)
    return None

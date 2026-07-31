"""Version and dependency resolution for worktree islands."""
import os

from version_stamp.core.logging import VMN_LOGGER


def resolve_version_source(vmn_ctx, source):
    if source["type"] != "version":
        return True
    resolved = version_app_data(vmn_ctx, source["ref"])
    if resolved is None:
        VMN_LOGGER.error(
            f"Version {source['ref']} of {vmn_ctx.vcs.name} was not found"
        )
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
    return _collect_deps(app_data.get("changesets", {}))


def deps_from_configured(vmn_ctx):
    configured = getattr(vmn_ctx.vcs, "configured_deps", {})
    actual = getattr(vmn_ctx.vcs, "actual_deps_state", {})
    raw_deps = {}
    for rel_path, conf in configured.items():
        if rel_path == ".":
            continue
        info = {
            "remote": conf.get("remote"),
            "branch": conf.get("branch"),
            "rel_path": rel_path,
        }
        if rel_path in actual:
            info["hash"] = actual[rel_path].get("hash")
            info["remote"] = info["remote"] or actual[rel_path].get("remote")
        raw_deps[rel_path] = info
    return _collect_deps(raw_deps, already_normalized=True)


def _collect_deps(raw_deps, already_normalized=False):
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
        if already_normalized:
            info = dict(raw_info)
        else:
            info = {
                "hash": raw_info.get("hash"),
                "remote": raw_info.get("remote"),
                "branch": raw_info.get("branch"),
                "rel_path": rel_path,
            }
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

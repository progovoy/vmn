#!/usr/bin/env python3
"""Worktree-based development islands for parallel feature work."""
import datetime
import json
import os
import shutil
import subprocess

from version_stamp.core.logging import VMN_LOGGER

ISLANDS_DIR_DEFAULT = "../vmn-islands"
ISLAND_MANIFEST_FILENAME = "island.json"
WORKTREE_READONLY_MARKER = ".worktree-readonly"


def handle_worktrees(vmn_ctx):
    action = vmn_ctx.args.action
    if action == "create":
        return worktree_create(vmn_ctx)
    elif action == "list":
        return worktree_list(vmn_ctx)
    elif action == "remove":
        return worktree_remove(vmn_ctx)

    VMN_LOGGER.error(f"Unknown worktrees action: {action}")
    return 1


def worktree_create(vmn_ctx):
    args = vmn_ctx.args
    base_path = os.path.abspath(
        os.path.join(vmn_ctx.vcs.vmn_root_path, args.base_path)
    )
    island_name = _resolve_island_name(args)
    island_path = os.path.join(base_path, island_name)

    if os.path.exists(island_path):
        VMN_LOGGER.error(f"Island directory already exists: {island_path}")
        return 1

    source = _resolve_source(args)
    if source is None:
        return 1

    main_repo_path = vmn_ctx.vcs.vmn_root_path
    current_branch = _git_current_branch(main_repo_path)
    if current_branch is None:
        VMN_LOGGER.error("Cannot determine current branch in main repo")
        return 1

    os.makedirs(island_path, exist_ok=True)

    repo_name = os.path.basename(main_repo_path)
    main_dest = os.path.join(island_path, repo_name)
    island_branch = f"island/{island_name}/{current_branch}"

    ret = _create_main_worktree(main_repo_path, main_dest, island_branch, source)
    if ret != 0:
        shutil.rmtree(island_path, ignore_errors=True)
        return 1

    remote_url = _git_remote_url(main_repo_path)

    deps = _resolve_deps(vmn_ctx, source)
    editable_deps = set(args.editable_dep or [])
    shallow = args.shallow_deps

    dep_manifests = {}
    for dep_name, dep_info in deps.items():
        dep_dest = os.path.join(island_path, dep_name)
        dep_repo_path = _find_dep_repo_path(vmn_ctx, dep_info)

        if dep_repo_path is None or not os.path.isdir(dep_repo_path):
            if shallow:
                ret = _shallow_clone_dep(dep_info, dep_dest)
            else:
                VMN_LOGGER.error(
                    f"Dependency repo not found locally: {dep_name}. "
                    f"Use --shallow-deps to clone from remote."
                )
                _cleanup_island(main_repo_path, island_path, island_branch, dep_manifests)
                return 1
        else:
            editable = dep_name in editable_deps
            ret = _create_dep_worktree(
                dep_repo_path, dep_dest, dep_info, island_name, editable
            )

        if ret != 0:
            _cleanup_island(main_repo_path, island_path, island_branch, dep_manifests)
            return 1

        dep_branch = None
        if dep_name in editable_deps:
            dep_branch = f"island/{island_name}/{dep_name}"

        dep_manifests[dep_name] = {
            "path": dep_dest,
            "hash": dep_info.get("hash"),
            "branch": dep_branch,
            "remote": dep_info.get("remote"),
            "editable": dep_name in editable_deps,
        }

    if args.no_stamp:
        marker_path = os.path.join(main_dest, ".vmn", WORKTREE_READONLY_MARKER)
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w") as f:
            f.write("")

    version = _resolve_version_string(vmn_ctx, source)

    manifest = {
        "name": island_name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "app_name": vmn_ctx.vcs.name,
        "version": version,
        "base_path": island_path,
        "source": source,
        "main_repo": {
            "path": main_dest,
            "branch": island_branch,
            "original_branch": current_branch,
            "remote": remote_url,
        },
        "deps": dep_manifests,
        "readonly": args.no_stamp,
        "shallow_deps": shallow,
    }

    manifest_path = os.path.join(island_path, ISLAND_MANIFEST_FILENAME)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(json.dumps(manifest, indent=2))
    return 0


def worktree_list(vmn_ctx):
    base_path = os.path.abspath(
        os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
    )

    if not os.path.isdir(base_path):
        VMN_LOGGER.info("No islands found")
        return 0

    islands = []
    for entry in sorted(os.listdir(base_path)):
        manifest_path = os.path.join(base_path, entry, ISLAND_MANIFEST_FILENAME)
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                islands.append(json.load(f))

    if not islands:
        VMN_LOGGER.info("No islands found")
        return 0

    header = f"{'NAME':<30} {'APP':<20} {'VERSION':<15} {'SOURCE':<20} {'CREATED'}"
    print(header)
    print("-" * len(header))
    for m in islands:
        src = f"{m['source']['type']}:{m['source']['ref']}"
        print(
            f"{m['name']:<30} {m['app_name']:<20} "
            f"{m.get('version') or 'N/A':<15} {src:<20} {m['created_at']}"
        )

    return 0


def worktree_remove(vmn_ctx):
    name = vmn_ctx.args.name
    if not name:
        VMN_LOGGER.error("Island name is required for remove")
        return 1

    base_path = os.path.abspath(
        os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
    )
    island_path = os.path.join(base_path, name)
    manifest_path = os.path.join(island_path, ISLAND_MANIFEST_FILENAME)

    if not os.path.isfile(manifest_path):
        VMN_LOGGER.error(f"Island not found: {name}")
        return 1

    with open(manifest_path) as f:
        manifest = json.load(f)

    main_repo_path = vmn_ctx.vcs.vmn_root_path

    for dep_name, dep_info in manifest.get("deps", {}).items():
        dep_path = dep_info["path"]
        if os.path.isdir(dep_path):
            dep_repo_path = _find_dep_repo_path_by_name(vmn_ctx, dep_name)
            if dep_repo_path:
                _run_git(dep_repo_path, ["worktree", "remove", "--force", dep_path])
                if dep_info.get("branch"):
                    _run_git(dep_repo_path, ["branch", "-D", dep_info["branch"]])

    main_wt_path = manifest["main_repo"]["path"]
    if os.path.isdir(main_wt_path):
        _run_git(main_repo_path, ["worktree", "remove", "--force", main_wt_path])

    island_branch = manifest["main_repo"].get("branch")
    if island_branch:
        _run_git(main_repo_path, ["branch", "-D", island_branch])

    if os.path.isdir(island_path):
        shutil.rmtree(island_path)

    VMN_LOGGER.info(f"Removed island: {name}")
    return 0


def _resolve_island_name(args):
    if args.island_name:
        return args.island_name
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = getattr(args, "from_branch", None) or "head"
    safe_branch = branch.replace("/", "-").replace("\\", "-")
    return f"{safe_branch}-{timestamp}"


def _resolve_source(args):
    from_version = getattr(args, "from_version", None)
    from_branch = getattr(args, "from_branch", None)

    if from_version:
        return {"type": "version", "ref": from_version}
    elif from_branch:
        return {"type": "branch", "ref": from_branch}
    else:
        return {"type": "head", "ref": "HEAD"}


def _resolve_version_string(vmn_ctx, source):
    if source["type"] == "version":
        return source["ref"]
    try:
        ver_infos = vmn_ctx.vcs.ver_infos_from_repo
        tag_name = vmn_ctx.vcs.selected_tag
        if tag_name and tag_name in ver_infos and ver_infos[tag_name]["ver_info"]:
            return ver_infos[tag_name]["ver_info"]["stamping"]["app"]["_version"]
    except Exception:
        pass
    return None


def _resolve_deps(vmn_ctx, source):
    if source["type"] == "version":
        deps = _deps_from_version(vmn_ctx, source["ref"])
        if deps:
            return deps
    return _deps_from_configured(vmn_ctx)


def _deps_from_version(vmn_ctx, version):
    try:
        tag_name, ver_infos = vmn_ctx.vcs.get_version_info_from_verstr(version)
        if tag_name in ver_infos and ver_infos[tag_name]["ver_info"]:
            changesets = ver_infos[tag_name]["ver_info"]["stamping"]["app"].get(
                "changesets", {}
            )
            deps = {}
            for rel_path, info in changesets.items():
                if rel_path == ".":
                    continue
                dep_name = os.path.basename(rel_path.rstrip("/"))
                deps[dep_name] = {
                    "hash": info.get("hash"),
                    "remote": info.get("remote"),
                    "branch": info.get("branch"),
                    "rel_path": rel_path,
                }
            return deps
    except Exception:
        VMN_LOGGER.debug("Failed to resolve deps from version", exc_info=True)
    return {}


def _deps_from_configured(vmn_ctx):
    deps = {}
    configured = getattr(vmn_ctx.vcs, "configured_deps", {})
    actual = getattr(vmn_ctx.vcs, "actual_deps_state", {})

    for rel_path, conf in configured.items():
        if rel_path == ".":
            continue
        dep_name = os.path.basename(rel_path.rstrip("/"))
        info = {
            "remote": conf.get("remote"),
            "branch": conf.get("branch"),
            "rel_path": rel_path,
        }
        if rel_path in actual:
            info["hash"] = actual[rel_path].get("hash")
            if not info["remote"]:
                info["remote"] = actual[rel_path].get("remote")
        deps[dep_name] = info

    return deps


def _find_dep_repo_path(vmn_ctx, dep_info):
    rel_path = dep_info.get("rel_path")
    if rel_path:
        full_path = os.path.join(vmn_ctx.vcs.vmn_root_path, rel_path)
        if os.path.isdir(full_path):
            return full_path
    return None


def _find_dep_repo_path_by_name(vmn_ctx, dep_name):
    configured = getattr(vmn_ctx.vcs, "configured_deps", {})
    for rel_path in configured:
        if rel_path == ".":
            continue
        if os.path.basename(rel_path.rstrip("/")) == dep_name:
            full_path = os.path.join(vmn_ctx.vcs.vmn_root_path, rel_path)
            if os.path.isdir(full_path):
                return full_path
    return None


def _git_current_branch(repo_path):
    result = _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
    if result and result.returncode == 0:
        branch = result.stdout.strip()
        if branch == "HEAD":
            return None
        return branch
    return None


def _git_remote_url(repo_path):
    result = _run_git(repo_path, ["remote", "get-url", "origin"])
    if result and result.returncode == 0:
        return result.stdout.strip()
    return None


def _create_main_worktree(repo_path, dest_path, branch_name, source):
    start_point = None
    if source["type"] == "branch":
        start_point = source["ref"]

    cmd = ["worktree", "add", "-b", branch_name, dest_path]
    if start_point:
        cmd.append(start_point)

    result = _run_git(repo_path, cmd)
    if result is None or result.returncode != 0:
        err_msg = result.stderr.strip() if result else "unknown error"
        VMN_LOGGER.error(f"Failed to create main worktree: {err_msg}")
        return 1
    return 0


def _create_dep_worktree(repo_path, dest_path, dep_info, island_name, editable):
    target_hash = dep_info.get("hash")

    if editable:
        dep_name = os.path.basename(dest_path)
        branch_name = f"island/{island_name}/{dep_name}"
        cmd = ["worktree", "add", "-b", branch_name, dest_path]
        if target_hash:
            cmd.append(target_hash)
    else:
        cmd = ["worktree", "add", "--detach", dest_path]
        if target_hash:
            cmd.append(target_hash)

    result = _run_git(repo_path, cmd)
    if result is None or result.returncode != 0:
        err_msg = result.stderr.strip() if result else "unknown error"
        VMN_LOGGER.error(
            f"Failed to create dep worktree at {dest_path}: {err_msg}"
        )
        return 1
    return 0


def _shallow_clone_dep(dep_info, dest_path):
    remote = dep_info.get("remote")
    if not remote:
        VMN_LOGGER.error("No remote URL for shallow clone")
        return 1

    cmd = ["git", "clone", "--depth", "1"]
    branch = dep_info.get("branch")
    if branch:
        cmd += ["--branch", branch]
    cmd += [remote, dest_path]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        VMN_LOGGER.error(f"Failed to shallow clone: {result.stderr.strip()}")
        return 1

    target_hash = dep_info.get("hash")
    if target_hash and not branch:
        fetch_result = subprocess.run(
            ["git", "-C", dest_path, "fetch", "--depth", "1", "origin", target_hash],
            capture_output=True, text=True,
        )
        if fetch_result.returncode == 0:
            subprocess.run(
                ["git", "-C", dest_path, "checkout", target_hash],
                capture_output=True, text=True,
            )

    return 0


def _cleanup_island(main_repo_path, island_path, island_branch, dep_manifests):
    for dep_name, dep_info in dep_manifests.items():
        dep_path = dep_info["path"]
        if dep_info.get("branch"):
            _run_git(main_repo_path, ["worktree", "remove", "--force", dep_path])
            _run_git(main_repo_path, ["branch", "-D", dep_info["branch"]])

    main_dest = os.path.join(island_path, "main-repo")
    if os.path.isdir(main_dest):
        _run_git(main_repo_path, ["worktree", "remove", "--force", main_dest])
    _run_git(main_repo_path, ["branch", "-D", island_branch])
    shutil.rmtree(island_path, ignore_errors=True)


def _run_git(repo_path, args):
    cmd = ["git", "-C", repo_path] + args
    try:
        return subprocess.run(cmd, capture_output=True, text=True)
    except Exception as e:
        VMN_LOGGER.debug(f"git command failed: {cmd} - {e}")
        return None

#!/usr/bin/env python3
"""`vmn worktrees create`: build an island of worktrees for the app and its deps."""
import datetime
import json
import os
import shutil

from version_stamp.cli.worktree_git import (
    cleanup_island as _cleanup_island,
)
from version_stamp.cli.worktree_git import (
    create_dep_worktree as _create_dep_worktree,
)
from version_stamp.cli.worktree_git import (
    create_main_worktree as _create_main_worktree,
)
from version_stamp.cli.worktree_git import (
    git_current_branch as _git_current_branch,
)
from version_stamp.cli.worktree_git import (
    git_remote_url as _git_remote_url,
)
from version_stamp.cli.worktree_git import (
    shallow_clone_dep as _shallow_clone_dep,
)
from version_stamp.cli.worktree_sources import (
    find_dep_repo_path as _find_dep_repo_path,
)
from version_stamp.cli.worktree_sources import (
    resolve_deps as _resolve_deps,
)
from version_stamp.cli.worktree_sources import (
    resolve_version_source as _resolve_version_source,
)
from version_stamp.cli.worktree_state import (
    write_island_markers as _write_island_markers,
)
from version_stamp.cli.worktree_state import (
    write_manifest as _write_manifest,
)
from version_stamp.core.logging import VMN_LOGGER

def worktree_create(vmn_ctx):
    args = vmn_ctx.args
    main_repo_path = vmn_ctx.vcs.vmn_root_path
    base_path = os.path.abspath(os.path.join(main_repo_path, args.base_path))
    island_name = _resolve_island_name(args)
    island_path = os.path.join(base_path, island_name)
    if os.path.exists(island_path):
        VMN_LOGGER.error(f"Island directory already exists: {island_path}")
        return 1

    source = _resolve_source(args)
    if not _resolve_version_source(vmn_ctx, source):
        return 1
    deps = _resolve_deps(vmn_ctx, source)
    if deps is None:
        return 1
    editable_deps = set(args.editable_dep or [])
    unknown_editable = editable_deps - set(deps)
    if unknown_editable:
        names = ", ".join(sorted(unknown_editable))
        VMN_LOGGER.error(f"Unknown --editable-dep: {names}")
        return 1

    current_branch = _git_current_branch(main_repo_path)
    if current_branch is None:
        VMN_LOGGER.error("Cannot determine current branch in main repo")
        return 1

    os.makedirs(island_path)
    main_dest = os.path.join(island_path, os.path.basename(main_repo_path))
    island_branch = f"island/{island_name}/{current_branch}"
    if _create_main_worktree(main_repo_path, main_dest, island_branch, source) != 0:
        shutil.rmtree(island_path, ignore_errors=True)
        return 1

    manifest = _new_manifest(
        vmn_ctx,
        island_name,
        island_path,
        source,
        main_repo_path,
        main_dest,
        island_branch,
        current_branch,
    )
    _write_manifest(manifest)

    for dep_name, dep_info in deps.items():
        if dep_name in editable_deps:
            dep_branch = f"island/{island_name}/{dep_name}"
        else:
            dep_branch = None
        dep_dest = os.path.join(island_path, dep_name)
        source_path = _find_dep_repo_path(vmn_ctx, dep_info)
        if source_path:
            ret = _create_dep_worktree(source_path, dep_dest, dep_info, dep_branch)
        elif args.shallow_deps:
            ret = _shallow_clone_dep(dep_info, dep_dest, dep_branch)
        else:
            VMN_LOGGER.error(
                f"Dependency repo not found locally: {dep_name}. "
                "Use --shallow-deps to clone from remote."
            )
            ret = 1

        if ret != 0:
            if not _cleanup_island(
                main_repo_path,
                main_dest,
                island_branch,
                manifest["deps"],
            ):
                _write_manifest(manifest)
            return 1

        manifest["deps"][dep_name] = {
            "path": dep_dest,
            "hash": dep_info.get("hash"),
            "branch": dep_branch,
            "remote": dep_info.get("remote"),
            "rel_path": dep_info.get("rel_path"),
            "source_path": source_path,
            "editable": dep_branch is not None,
        }
        _write_manifest(manifest)

    _write_island_markers(
        [main_dest, *(dep["path"] for dep in manifest["deps"].values())],
    )
    manifest_json = json.dumps(manifest, indent=2)
    print(manifest_json)
    return 0


def _new_manifest(
    vmn_ctx,
    island_name,
    island_path,
    source,
    main_repo_path,
    main_dest,
    island_branch,
    current_branch,
):
    return {
        "name": island_name,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        "app_name": vmn_ctx.vcs.name,
        "version": _resolve_version_string(vmn_ctx, source),
        "base_path": island_path,
        "source": source,
        "main_repo": {
            "path": main_dest,
            "source_path": main_repo_path,
            "branch": island_branch,
            "original_branch": current_branch,
            "remote": _git_remote_url(main_repo_path),
        },
        "deps": {},
        "shallow_deps": vmn_ctx.args.shallow_deps,
    }


def _resolve_island_name(args):
    if args.island_name:
        return args.island_name
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = getattr(args, "from_branch", None) or "head"
    return f"{branch.replace('/', '-').replace(chr(92), '-')}-{timestamp}"


def _resolve_source(args):
    if getattr(args, "from_version", None):
        return {"type": "version", "ref": args.from_version}
    if getattr(args, "from_branch", None):
        return {"type": "branch", "ref": args.from_branch}
    return {"type": "head", "ref": "HEAD"}


def _resolve_version_string(vmn_ctx, source):
    if source["type"] == "version":
        return source["ref"]
    try:
        tag = vmn_ctx.vcs.selected_tag
        info = vmn_ctx.vcs.ver_infos_from_repo[tag]["ver_info"]
        return info["stamping"]["app"]["_version"]
    except Exception:
        return None

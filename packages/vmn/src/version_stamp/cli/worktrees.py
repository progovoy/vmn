#!/usr/bin/env python3
"""Worktree islands: list, remove, and dispatch to create."""
import os

from version_stamp.cli.worktree_git import (
    cleanup_island,
    remove_readonly_remote_if_unused,
    source_repo_from_worktree,
)
from version_stamp.cli.worktree_git import (
    run_git as _run_git,
)
from version_stamp.cli.worktree_state import (
    ISLAND_MANIFEST_FILENAME,
    island_dir,
    read_manifest,
)
from version_stamp.cli.worktree_create import worktree_create
from version_stamp.cli.worktree_freeze import worktree_freeze
from version_stamp.cli.worktree_pull import worktree_pull
from version_stamp.compat.worktree_manifest import legacy_dep_source
from version_stamp.core.logging import VMN_LOGGER


def handle_worktrees(vmn_ctx):
    handlers = {
        "create": worktree_create,
        "list": worktree_list,
        "remove": worktree_remove,
        "freeze": worktree_freeze,
        "pull": worktree_pull,
    }
    return handlers[vmn_ctx.args.action](vmn_ctx)


def worktree_list(vmn_ctx):
    base_path = os.path.abspath(
        os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
    )
    islands = []
    if os.path.isdir(base_path):
        for entry in sorted(os.listdir(base_path)):
            path = os.path.join(base_path, entry, ISLAND_MANIFEST_FILENAME)
            if not os.path.isfile(path):
                continue
            manifest = read_manifest(path)
            if manifest is None:
                VMN_LOGGER.warning(f"Skipping corrupt manifest: {path}")
            else:
                islands.append(manifest)
    if not islands:
        VMN_LOGGER.info("No islands found")
        return 0

    header = f"{'NAME':<30} {'APP':<20} {'VERSION':<15} {'SOURCE':<20} {'CREATED'}"
    print(header)
    print("-" * len(header))
    for manifest in islands:
        source = manifest.get("source", {})
        source_text = f"{source.get('type', '?')}:{source.get('ref', '?')}"
        print(
            f"{manifest.get('name', '?'):<30} "
            f"{manifest.get('app_name') or 'N/A':<20} "
            f"{manifest.get('version') or 'N/A':<15} "
            f"{source_text:<20} {manifest.get('created_at', 'N/A')}"
        )
    return 0


def worktree_remove(vmn_ctx):
    name = vmn_ctx.args.name
    island_path = island_dir(vmn_ctx, name)
    manifest_path = os.path.join(island_path, ISLAND_MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        VMN_LOGGER.error(f"Island not found: {name}")
        return 1
    manifest = read_manifest(manifest_path)
    if manifest is None:
        VMN_LOGGER.error(f"Corrupt island manifest: {manifest_path}")
        return 1

    main = manifest["main_repo"]
    main_source = main.get("source_path", vmn_ctx.vcs.vmn_root_path)
    deps = {
        key: {**dep, "source_path": _dep_source(dep, main_source)}
        for key, dep in manifest.get("deps", {}).items()
    }
    if not cleanup_island(
        main_source, main["path"], main.get("branch"), deps, _run_git,
        island_path=island_path,
    ):
        VMN_LOGGER.error(
            f"Island cleanup incomplete; retry metadata kept at {manifest_path}"
        )
        return 1

    for repo in _source_repos(manifest, main_source):
        remove_readonly_remote_if_unused(repo)
    VMN_LOGGER.info(f"Removed island: {name}")
    return 0


def _dep_source(dep, main_source):
    return (
        dep.get("source_path")
        or source_repo_from_worktree(dep["path"], _run_git)
        or legacy_dep_source(main_source, dep)
    )


def _source_repos(manifest, main_source):
    deps = manifest.get("deps", {}).values()
    return [main_source, *(dep["source_path"] for dep in deps if dep.get("source_path"))]

#!/usr/bin/env python3
"""Worktree islands: list, remove, and dispatch to create."""
import json
import os
import shutil

from version_stamp.cli.worktree_git import (
    remove_readonly_remote_if_unused,
    remove_registered_worktree,
    source_repo_from_worktree,
)
from version_stamp.cli.worktree_git import (
    run_git as _run_git,
)
from version_stamp.cli.worktree_state import (
    ISLAND_MANIFEST_FILENAME,
)
from version_stamp.cli.worktree_create import worktree_create
from version_stamp.cli.worktree_freeze import worktree_freeze
from version_stamp.cli.worktree_pull import worktree_pull
from version_stamp.compat.worktree_manifest import legacy_dep_source
from version_stamp.core.logging import VMN_LOGGER

ISLANDS_DIR_DEFAULT = "../vmn-islands"


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
            if os.path.isfile(path):
                try:
                    with open(path) as stream:
                        islands.append(json.load(stream))
                except (json.JSONDecodeError, OSError):
                    VMN_LOGGER.warning(f"Skipping corrupt manifest: {path}")
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
    base_path = os.path.abspath(
        os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
    )
    island_path = os.path.join(base_path, name)
    manifest_path = os.path.join(island_path, ISLAND_MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        VMN_LOGGER.error(f"Island not found: {name}")
        return 1
    with open(manifest_path) as stream:
        manifest = json.load(stream)

    success = True
    main_source = manifest["main_repo"].get("source_path", vmn_ctx.vcs.vmn_root_path)
    for dep in manifest.get("deps", {}).values():
        source_path = (
            dep.get("source_path")
            or source_repo_from_worktree(dep["path"], _run_git)
            or legacy_dep_source(main_source, dep)
        )
        if source_path and not remove_registered_worktree(
            source_path, dep["path"], dep.get("branch"), _run_git
        ):
            success = False

    main = manifest["main_repo"]
    if not remove_registered_worktree(
        main_source, main["path"], main.get("branch"), _run_git
    ):
        success = False
    if not success:
        VMN_LOGGER.error(
            f"Island cleanup incomplete; retry metadata kept at {manifest_path}"
        )
        return 1

    for repo in _source_repos(manifest, main_source):
        remove_readonly_remote_if_unused(repo)
    shutil.rmtree(island_path, ignore_errors=True)
    VMN_LOGGER.info(f"Removed island: {name}")
    return 0


def _source_repos(manifest, main_source):
    deps = manifest.get("deps", {}).values()
    return [main_source, *(dep["source_path"] for dep in deps if dep.get("source_path"))]

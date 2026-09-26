#!/usr/bin/env python3
"""`vmn worktrees create`: build an island of worktrees for the app and its deps."""
import datetime
import json
import os
import shutil

# The underscore aliases are the names tests monkeypatch.
from version_stamp.cli.worktree_git import (
    cleanup_island as _cleanup_island,
    create_dep_worktree as _create_dep_worktree,
    create_main_worktree as _create_main_worktree,
    ensure_readonly_remote,
    fetch_readonly_branch,
    git_current_branch as _git_current_branch,
    git_head,
    git_remote_url as _git_remote_url,
    is_dirty,
    remove_readonly_remote_if_unused,
    shallow_clone_dep as _shallow_clone_dep,
    track_privately,
)
from version_stamp.cli.worktree_sources import (
    find_dep_repo_path as _find_dep_repo_path,
    resolve_deps as _resolve_deps,
    resolve_version_source as _resolve_version_source,
)
from version_stamp.cli.worktree_state import (
    island_branch_name as _island_branch_name,
    write_manifest as _write_manifest,
)
from version_stamp.core.constants import VMN_READONLY_REMOTE
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

    current_branch = _git_current_branch(main_repo_path)
    if current_branch is None:
        VMN_LOGGER.error("Cannot determine current branch in main repo")
        return 1

    dep_sources = {name: _find_dep_repo_path(vmn_ctx, dep) for name, dep in deps.items()}
    _warn_about_uncommitted_changes(main_repo_path, dep_sources.values())

    layout = _island_layout(main_repo_path, deps, island_path)
    os.makedirs(island_path)
    main_dest = layout["."]
    main_source_branch = _main_source_branch(source, current_branch)
    island_branch = _island_branch_name(
        island_name, main_source_branch or current_branch
    )
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
        main_source_branch,
    )
    if main_source_branch:
        upstream = _track_source(main_repo_path, island_branch, main_source_branch)
        if upstream is None:
            _rollback(main_repo_path, main_dest, island_branch, manifest, dep_sources)
            return 1
        manifest["main_repo"]["upstream"] = upstream
    _write_manifest(manifest)

    for dep_name, dep in deps.items():
        entry = _add_dep(args, island_name, layout[dep_name], dep_name, dep, dep_sources)
        if entry is None:
            _rollback(main_repo_path, main_dest, island_branch, manifest, dep_sources)
            return 1
        manifest["deps"][dep_name] = entry
        _write_manifest(manifest)

    print(json.dumps(manifest, indent=2))
    return 0


def _main_source_branch(source, current_branch):
    """The branch `wt pull` rebases A onto; None for a --from-version island."""
    if source["type"] == "branch":
        return source["ref"]
    if source["type"] == "head":
        return current_branch
    return None


def _warn_about_uncommitted_changes(main_repo_path, dep_paths):
    paths = [main_repo_path, *(path for path in dep_paths if path)]
    dirty = [path for path in paths if is_dirty(path)]
    if dirty:
        VMN_LOGGER.warning(
            "Uncommitted changes are not carried into the island: "
            + ", ".join(dirty)
        )


def _mirror_source(repo_path, source_branch):
    """Fetch *source_branch* through the read-only remote; its ref, or None."""
    if ensure_readonly_remote(repo_path) and fetch_readonly_branch(
        repo_path, source_branch
    ):
        return f"{VMN_READONLY_REMOTE}/{source_branch}"
    return None


def _track_source(repo_path, private_branch, source_branch, mirrored=None):
    """Make *private_branch* follow *source_branch*; its upstream, or None."""
    upstream = mirrored or _mirror_source(repo_path, source_branch) or source_branch
    return upstream if track_privately(repo_path, private_branch, upstream) else None


def _island_layout(main_repo_path, deps, island_path):
    """Where each checkout goes, keeping the source's relative layout.

    Configured dep paths are relative to the main repo (e.g. ../libs/B), so
    everything is placed under the island at its path relative to the common
    parent of the main repo and all deps. Returns {".": main, dep_name: path}.
    """
    sources = {".": os.path.realpath(main_repo_path)}
    for dep_name, dep in deps.items():
        sources[dep_name] = os.path.realpath(
            os.path.join(main_repo_path, dep["rel_path"])
        )
    anchor = os.path.commonpath(list(sources.values()))
    if anchor == sources["."]:
        anchor = os.path.dirname(anchor)
    return {
        name: os.path.join(island_path, os.path.relpath(path, anchor))
        for name, path in sources.items()
    }


def _add_dep(args, island_name, dep_dest, dep_name, dep, dep_sources):
    source_path = dep_sources[dep_name]
    source_branch = dep["source_branch"]
    dep_branch = (
        _island_branch_name(island_name, source_branch) if source_branch else None
    )
    mirrored = None
    if source_path:
        if dep["fetch"]:
            mirrored = _mirror_source(source_path, source_branch)
            if mirrored is None:
                VMN_LOGGER.error(
                    f"Branch {source_branch} of dependency {dep_name} "
                    "was not found on its remote"
                )
                return None
        ret = _create_dep_worktree(source_path, dep_dest, dep, dep_branch)
    elif args.shallow_deps:
        ret = _shallow_clone_dep(dep, dep_dest, dep_branch)
    else:
        VMN_LOGGER.error(
            f"Dependency repo not found locally: {dep_name}. "
            "Use --shallow-deps to clone from remote."
        )
        return None
    if ret != 0:
        return None

    upstream = None
    if dep_branch:
        owner = source_path or dep_dest
        upstream = _track_source(owner, dep_branch, source_branch, mirrored)
        if upstream is None:
            return None
    return {
        "path": dep_dest,
        "hash": git_head(dep_dest),
        "branch": dep_branch,
        "source_branch": source_branch,
        "upstream": upstream,
        "remote": dep.get("remote"),
        "rel_path": dep.get("rel_path"),
        "source_path": source_path,
    }


def _rollback(main_repo_path, main_dest, island_branch, manifest, dep_sources):
    """Undo a half-built island; keep its manifest when cleanup is incomplete."""
    if not _cleanup_island(
        main_repo_path,
        main_dest,
        island_branch,
        manifest["deps"],
        island_path=manifest["base_path"],
    ):
        _write_manifest(manifest)
        return
    for repo in (main_repo_path, *(p for p in dep_sources.values() if p)):
        remove_readonly_remote_if_unused(repo)


def _new_manifest(
    vmn_ctx,
    island_name,
    island_path,
    source,
    main_repo_path,
    main_dest,
    island_branch,
    current_branch,
    source_branch,
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
            "source_branch": source_branch,
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

#!/usr/bin/env python3
"""Migrate branch-specific confs to the canonical ``branch_conf/`` layout.

Old conventions (flat ``{branch-dashes}_conf.yml`` and legacy nested
``{branch}/conf.yml``) are moved to ``branch_conf/{branch}/conf.yml`` on any
stamp. Migration is purely local (uses only already-known refs), idempotent,
and never destroys data it cannot safely place.
"""
import os

from version_stamp.core.constants import BRANCH_CONF_DIR
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import (
    branch_conf_canonical_path,
    branch_to_conf_prefix,
)

_PRUNE_DIRS = {BRANCH_CONF_DIR, "verinfo", "root_verinfo"}


def migrate_branch_confs(backend, vmn_root_path, dry_run=False):
    """Move every app's branch confs to the canonical layout.

    Returns a list of ``(old_path, new_path)`` moves (for remapping paths that
    the caller tracks); under ``dry_run`` the moves are only planned and
    nothing is touched. Runs for all apps regardless of which one is stamped.
    """
    vmn_dir = os.path.join(vmn_root_path, ".vmn")
    if not os.path.isdir(vmn_dir):
        return []

    repo = backend._be
    known_branches = _known_branches(repo)

    moves = []
    for app_dir in _discover_app_dirs(vmn_dir):
        moves.extend(_migrate_app_dir(repo, app_dir, known_branches, dry_run))
    return moves


def _discover_app_dirs(vmn_dir):
    app_dirs = []
    for dirpath, dirnames, filenames in os.walk(vmn_dir):
        dirnames[:] = [d for d in dirnames if d not in _PRUNE_DIRS]
        if "conf.yml" in filenames or "root_conf.yml" in filenames:
            app_dirs.append(dirpath)
    return app_dirs


def _is_app_dir(path):
    return os.path.isfile(os.path.join(path, "conf.yml")) or os.path.isfile(
        os.path.join(path, "root_conf.yml")
    )


def _split_conf_filename(name):
    """Return ``(leaf, is_root)`` for a branch conf filename, else None."""
    if name in ("conf.yml", "root_conf.yml"):
        return None
    if name.endswith("_root_conf.yml"):
        return name[: -len("_root_conf.yml")], True
    if name.endswith("_conf.yml"):
        return name[: -len("_conf.yml")], False
    return None


def _flat_confs(app_dir):
    """Yield ``(path, is_root, prefix)`` for flat branch confs in ``app_dir``."""
    for name in sorted(os.listdir(app_dir)):
        full = os.path.join(app_dir, name)
        if not os.path.isfile(full):
            continue
        parsed = _split_conf_filename(name)
        if parsed:
            leaf, is_root = parsed
            yield full, is_root, leaf


def _legacy_confs(app_dir):
    """Yield ``(path, is_root, branch)`` for legacy nested branch confs.

    Nested app dirs (root-app services) and special dirs are pruned so their
    own confs are handled independently.
    """
    for dirpath, dirnames, filenames in os.walk(app_dir):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _PRUNE_DIRS
            and not _is_app_dir(os.path.join(dirpath, d))
        ]
        if dirpath == app_dir:
            continue
        rel_dir = os.path.relpath(dirpath, app_dir)
        for name in sorted(filenames):
            parsed = _split_conf_filename(name)
            if not parsed:
                continue
            leaf, is_root = parsed
            branch = os.path.join(rel_dir, leaf).replace(os.sep, "/")
            yield os.path.join(dirpath, name), is_root, branch


def _migrate_app_dir(repo, app_dir, known_branches, dry_run):
    sources = {}
    for path, is_root, prefix in _flat_confs(app_dir):
        branch = _resolve_flat_branch(prefix, known_branches)
        if branch is None:
            continue
        sources.setdefault((branch, is_root), {}).setdefault("flat", path)
    for path, is_root, branch in _legacy_confs(app_dir):
        sources.setdefault((branch, is_root), {}).setdefault("legacy", path)

    moves = []
    for (branch, is_root), by_conv in sources.items():
        canonical = branch_conf_canonical_path(app_dir, branch, root=is_root)
        flat = by_conv.get("flat")
        legacy = by_conv.get("legacy")

        if os.path.isfile(canonical):
            for dup in (flat, legacy):
                if dup:
                    _stage_delete(repo, dup, dry_run)
            if legacy and not dry_run:
                _prune_empty_dirs(os.path.dirname(legacy), app_dir)
            continue

        src = flat or legacy
        if _stage_move(repo, src, canonical, dry_run):
            moves.append((src, canonical))
        if flat and legacy:
            _stage_delete(repo, legacy, dry_run)
        if not dry_run:
            _prune_empty_dirs(os.path.dirname(src), app_dir)
            if legacy:
                _prune_empty_dirs(os.path.dirname(legacy), app_dir)
    return moves


def _resolve_flat_branch(prefix, known_branches):
    """Map a flat conf prefix to a branch name.

    A slashed branch whose dashed form matches wins over a literal branch of
    the same name; several slashed matches are ambiguous and skipped.
    """
    slashed = {
        b
        for b in known_branches
        if b != prefix and branch_to_conf_prefix(b) == prefix
    }
    if len(slashed) > 1:
        VMN_LOGGER.warning(
            f"Ambiguous branch conf prefix '{prefix}' matches "
            f"{sorted(slashed)}; leaving it in the flat layout."
        )
        return None
    if slashed:
        return next(iter(slashed))
    return prefix


def _known_branches(repo):
    branches = set()
    try:
        for head in repo.heads:
            branches.add(head.name)
    except Exception:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)
    try:
        for remote in repo.remotes:
            for ref in remote.refs:
                if ref.remote_head and ref.remote_head != "HEAD":
                    branches.add(ref.remote_head)
    except Exception:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)
    return branches


def _stage_move(repo, src, dst, dry_run):
    if dry_run:
        VMN_LOGGER.info(f"Would have migrated {src} -> {dst}")
        return True
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
    except OSError:
        VMN_LOGGER.warning(
            f"Failed to migrate {src} -> {dst}; leaving it in place.",
            exc_info=True,
        )
        return False
    _index_remove(repo, src)
    _index_add(repo, dst)
    return True


def _stage_delete(repo, path, dry_run):
    if dry_run:
        VMN_LOGGER.info(f"Would have removed duplicate branch conf {path}")
        return
    _index_remove(repo, path)
    try:
        os.remove(path)
    except OSError:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)


def _index_remove(repo, path):
    try:
        repo.index.remove([path], working_tree=False)
    except Exception:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)


def _index_add(repo, path):
    try:
        repo.index.add([path])
    except Exception:
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)


def _prune_empty_dirs(start_dir, stop_dir):
    cur = start_dir
    while cur != stop_dir and cur.startswith(stop_dir + os.sep):
        try:
            os.rmdir(cur)
        except OSError:
            break
        cur = os.path.dirname(cur)

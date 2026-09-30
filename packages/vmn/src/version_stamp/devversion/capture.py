"""Patch generation, diff-hash computation, and verstr formatting for dev versions."""
import hashlib
import os
import sys

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import yaml_safe_load
from version_stamp.devversion.untracked import (
    _ensure_trailing_newline,
    _hash_untracked_content,
    untracked_payload,
)

# Diff-hash prefix lengths tried, shortest first, when a verstr is taken by a
# snapshot with different content (a 7-hex prefix is only 28 bits).
_DIFF_HASH_LENGTHS = (7, 12, 16, 24, 32, 64)


def _generate_patches(backend, lightweight=False):
    """Generate patches for dirty working tree state.

    Args:
        backend: Git backend instance.
        lightweight: When True, skip the untracked tarball and keep only the
            untracked content hash. Much faster for large untracked files,
            suitable for ``show --dev`` where only a stable hash is needed.
    """
    patches = {}

    try:
        # Unstripped: a binary patch must end with its blank line.
        wt_diff = backend._be.git.diff(
            "--binary", "HEAD", strip_newline_in_stdout=False
        )
        if wt_diff.strip():
            patches["working_tree"] = _ensure_trailing_newline(wt_diff)
    except Exception:
        VMN_LOGGER.debug("Failed to generate working tree diff", exc_info=True)

    if backend.remote_active_branch is not None:
        try:
            local_commits_diff = backend._be.git.format_patch(
                "--stdout",
                f"{backend.remote_active_branch}..{backend.active_branch}",
            )
            if local_commits_diff.strip():
                patches["local_commits"] = _ensure_trailing_newline(local_commits_diff)
        except Exception:
            VMN_LOGGER.debug("Failed to generate local commits patch", exc_info=True)

    try:
        content_hash = _hash_untracked_content(backend.repo_path)
        if content_hash:
            patches["untracked_hash"] = content_hash
        if not lightweight:
            patches.update(untracked_payload(backend.repo_path))
    except Exception:
        VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)

    return patches


def _generate_dep_patches(vcs, lightweight=False):
    from version_stamp.backends.factory import get_client

    configured_deps = getattr(vcs, "configured_deps", None)
    if not configured_deps:
        return {}

    dep_patches = {}
    for dep_path in configured_deps:
        if dep_path == ".":
            continue
        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if not os.path.isdir(full_path):
            continue
        try:
            dep_be, err = get_client(full_path, vcs.be_type)
            if err or not dep_be:
                continue
            dp = _generate_patches(dep_be, lightweight=lightweight)
            if dp:
                dep_patches[dep_path] = dp
        except Exception:
            VMN_LOGGER.debug(
                f"Failed to generate patches for dep {dep_path}", exc_info=True
            )

    return dep_patches


def _compute_diff_hash(patches):
    """Full sha256 hex over a snapshot's content, or None for a clean tree."""
    h = hashlib.sha256()
    has_content = False
    for key in ("working_tree", "local_commits"):
        if patches.get(key):
            h.update(patches[key].encode())
            has_content = True
    if patches.get("untracked_hash"):
        h.update(patches["untracked_hash"])
        has_content = True

    for dep_path in sorted(patches.get("deps", {})):
        dp = patches["deps"][dep_path]
        for key in ("working_tree", "local_commits"):
            if dp.get(key):
                h.update(dp[key].encode())
                has_content = True
        if dp.get("untracked_hash"):
            h.update(dp["untracked_hash"])
            has_content = True

    return h.hexdigest() if has_content else None


def _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len=7):
    diff_part = diff_hash[:hash_len] if diff_hash else "0000000"
    return f"{base_version}-dev.{commit_hash[:7]}.{diff_part}"


def _compute_verstr(base_version, commit_hash, patches, hash_len=7):
    return _format_dev_verstr(
        base_version, commit_hash, _compute_diff_hash(patches), hash_len
    )


def _stored_metadata(storage, app_name, verstr):
    """``(exists, metadata dict)`` of the snapshot stored at *verstr*."""
    raw = storage.load_file(app_name, verstr, "metadata.yml")
    if raw is None:
        return False, {}
    try:
        meta = yaml_safe_load(raw)
    except Exception:
        meta = None
    return True, meta if isinstance(meta, dict) else {}


def _stored_diff_hash(storage, app_name, verstr):
    """``(exists, diff_hash)`` of the snapshot stored at *verstr*."""
    exists, meta = _stored_metadata(storage, app_name, verstr)
    return exists, meta.get("diff_hash")


def _unique_snapshot_verstr(
    storage, app_name, base_version, commit_hash, diff_hash, changesets=None
):
    """The shortest dev verstr that is free or already holds this exact state.

    A snapshot never overwrites a different one: on a prefix collision (or a
    legacy record that carries no ``diff_hash`` to compare) the diff hash is
    extended instead. With *changesets*, a record of the same diff at other
    repo commits is a collision too; without them only the diff counts.
    """
    # Imported here: version_stamp.snapshot.record imports this module.
    from version_stamp.snapshot.record import same_state

    verstr = _format_dev_verstr(base_version, commit_hash, diff_hash)
    if not diff_hash:
        return verstr
    for hash_len in _DIFF_HASH_LENGTHS:
        verstr = _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len)
        exists, stored = _stored_metadata(storage, app_name, verstr)
        if not exists or same_state(stored, diff_hash, changesets):
            return verstr
    return verstr


def _base_commit(backend, patches):
    """The commit a snapshot's patches apply to: the upstream when local
    commits are carried as a patch (they are replayed on top), else HEAD."""
    if patches.get("local_commits"):
        return backend._be.git.rev_parse(backend.remote_active_branch)
    return backend.changeset()


def gather_create_data(vcs, allow_clean=False, lightweight=False, status=None):
    """Gather common data needed by snapshot/experiment create.

    Returns (base_version, commit_hash, patches, dirty_states, ver_info, error_code).
    error_code is non-None when the caller should return early.

    When ``allow_clean`` is True a clean working tree is not an error: it yields
    empty patches (verstr gets a zeroed diff hash) so experiments can be recorded
    against committed code. Snapshots keep the clean-tree no-op.

    ``lightweight`` skips the untracked tarball (see :func:`untracked_payload`):
    the patches still carry everything the diff hash is computed from.
    ``status`` is a repo status the caller already computed with the same
    expected/optional sets, to spare a second one.
    """
    from version_stamp.cli.commands import _get_repo_status
    from version_stamp.cli.output import get_dirty_states

    expected_status = {"repo_tracked", "app_tracked"}
    optional_status = {
        "repos_exist_locally",
        "detached",
        "pending",
        "outgoing",
        "version_not_matched",
        "dirty_deps",
        "deps_synced_with_conf",
    }
    if status is None:
        status = _get_repo_status(vcs, expected_status, optional_status)
    if status.error:
        name = vcs.name or "<app_name>"
        VMN_LOGGER.error(
            f"Cannot create snapshot: '{name}' has not been stamped yet. "
            f"Run 'vmn stamp -r patch {name}' first."
        )
        return None, None, None, None, None, 1

    dirty_states = list(get_dirty_states(optional_status, status))

    ver_infos = vcs.ver_infos_from_repo
    tag_name = vcs.selected_tag
    if tag_name not in ver_infos:
        name = vcs.name or "<app_name>"
        VMN_LOGGER.error(
            f"No stamped version found for '{name}'. "
            f"Run 'vmn stamp -r patch {name}' first."
        )
        return None, None, None, None, None, 1

    ver_info = ver_infos[tag_name]["ver_info"]
    if vcs.root_context:
        base_version = str(ver_info["stamping"]["root_app"]["version"])
    else:
        base_version = ver_info["stamping"]["app"]["_version"]

    be = vcs.backend
    patches = _generate_patches(be, lightweight=lightweight)
    commit_hash = _base_commit(be, patches)
    dep_patches = _generate_dep_patches(vcs, lightweight=lightweight)
    if dep_patches:
        patches["deps"] = dep_patches

    has_content = any(k != "deps" for k in patches) or bool(dep_patches)
    if not patches or not has_content:
        if not allow_clean:
            print(
                "No local changes to snapshot (working tree is clean)",
                file=sys.stderr,
            )
            return None, None, None, None, None, 0

    return base_version, commit_hash, patches, dirty_states, ver_info, None

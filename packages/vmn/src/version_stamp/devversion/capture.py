"""Patch generation, diff-hash computation, and verstr formatting for dev versions."""
import os

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.untracked import (
    _collect_untracked_tarball,
    _ensure_trailing_newline,
    _hash_untracked_content,
    _untracked_stats,
    payload_from_tarball,
)
from version_stamp.snapshot.identity import _compute_diff_hash, _format_dev_verstr


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
        stats = _untracked_stats(backend.repo_path)
        content_hash = _hash_untracked_content(backend.repo_path, stats)
        if content_hash:
            patches["untracked_hash"] = content_hash
        if not lightweight:
            patches.update(
                payload_from_tarball(*_collect_untracked_tarball(backend.repo_path, stats))
            )
    except Exception:
        VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)

    return patches


def _dep_backends(vcs):
    """``{dep_path: backend}`` of the configured deps checked out on disk."""
    from version_stamp.backends.factory import get_client

    backends = {}
    for dep_path in vcs.configured_deps:
        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if dep_path == "." or not os.path.isdir(full_path):
            continue
        try:
            dep_be, err = get_client(full_path, vcs.be_type)
        except Exception:
            VMN_LOGGER.debug(f"Failed to open dep {dep_path}", exc_info=True)
            continue
        if not err and dep_be:
            backends[dep_path] = dep_be
    return backends


def _dep_patch_sets(vcs, lightweight):
    """``(dep_path, backend, patches)`` of every dep on disk."""
    for dep_path, dep_be in _dep_backends(vcs).items():
        try:
            dp = _generate_patches(dep_be, lightweight=lightweight)
        except Exception:
            _log_dep_failure(dep_path)
            continue
        yield dep_path, dep_be, dp


def _log_dep_failure(dep_path):
    VMN_LOGGER.debug(f"Failed to generate patches for dep {dep_path}", exc_info=True)


def _generate_dep_patches(vcs, lightweight=False):
    """``{dep_path: patches}`` of the dirty deps."""
    return {path: dp for path, _, dp in _dep_patch_sets(vcs, lightweight) if dp}


def _capture_deps(vcs, lightweight=False):
    """``(dep patches, dep base commits)``: the patches of the dirty deps and
    the commit every dep on disk sits at (see :func:`_base_commit`)."""
    dep_patches, dep_bases = {}, {}
    for dep_path, dep_be, dp in _dep_patch_sets(vcs, lightweight):
        try:
            dep_bases[dep_path] = _base_commit(dep_be, dp)
        except Exception:
            _log_dep_failure(dep_path)
            continue
        if dp:
            dep_patches[dep_path] = dp
    return dep_patches, dep_bases


def _compute_verstr(base_version, commit_hash, patches, hash_len=7):
    return _format_dev_verstr(
        base_version, commit_hash, _compute_diff_hash(patches), hash_len
    )


def _base_commit(backend, patches):
    """The commit a snapshot's patches apply to: the upstream when local
    commits are carried as a patch (they are replayed on top), else HEAD."""
    if patches.get("local_commits"):
        return backend._be.git.rev_parse(backend.remote_active_branch)
    return backend.changeset()


def gather_create_data(vcs, lightweight=False, status=None):
    """Gather common data needed by snapshot/experiment create.

    Returns (base_version, commit_hash, patches, dirty_states, ver_info, error_code).
    error_code is non-None when the caller should return early. A clean tree
    yields empty patches (the verstr gets a zeroed diff hash). ``patches``
    carries ``dep_base_commits``, the commit each dep on disk sits at.

    ``lightweight`` skips the untracked tarball (see :func:`untracked_payload`):
    the patches still carry everything the diff hash is computed from.
    ``status`` is a repo status the caller already computed with the same
    expected/optional sets, to spare a second one.
    """
    from version_stamp.stamping.repo_status import (
        READ_ONLY_EXPECTED,
        READ_ONLY_OPTIONAL,
        _get_repo_status,
        get_dirty_states,
    )

    if status is None:
        status = _get_repo_status(vcs, READ_ONLY_EXPECTED, READ_ONLY_OPTIONAL)
    if status.error:
        name = vcs.name or "<app_name>"
        VMN_LOGGER.error(
            f"Cannot create snapshot: '{name}' has not been stamped yet. "
            f"Run 'vmn stamp -r patch {name}' first."
        )
        return None, None, None, None, None, 1

    dirty_states = list(get_dirty_states(READ_ONLY_OPTIONAL, status))

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
    dep_patches, dep_bases = _capture_deps(vcs, lightweight=lightweight)
    if dep_patches:
        patches["deps"] = dep_patches
    if dep_bases:
        patches["dep_base_commits"] = dep_bases

    return base_version, commit_hash, patches, dirty_states, ver_info, None

#!/usr/bin/env python3
"""Snapshot storage and operations for dev versions."""
import datetime
import hashlib
import io
import json
import os
import shutil
import stat as stat_module
import subprocess
import sys
import tarfile
import tempfile

import yaml

# The storage backends live in their own modules; these names stay importable
# from here for existing callers.
from version_stamp.cli.snapshot_storage import SnapshotStorage  # noqa: F401
from version_stamp.cli.snapshot_storage_cached import (  # noqa: F401
    CachedSnapshotStorage,
    get_snapshot_storage,
)
from version_stamp.cli.snapshot_storage_files import atomic_write
from version_stamp.cli.snapshot_storage_files import (  # noqa: F401
    read_patches_from_dir as _read_patches_from_dir,
)
from version_stamp.cli.snapshot_storage_files import (  # noqa: F401
    write_patches_to_dir as _write_patches_to_dir,
)
from version_stamp.cli.snapshot_storage_local import (  # noqa: F401
    LocalSnapshotStorage,
)
from version_stamp.cli.snapshot_storage_s3 import S3SnapshotStorage  # noqa: F401
from version_stamp.core.logging import VMN_LOGGER, measure_runtime_decorator
from version_stamp.core.utils import now_iso, sha256_file

# These two are pure helpers that the core write path needs as well, so they
# live in core.utils now. The old private names stay importable from here.
_now_iso = now_iso
_sha256_file = sha256_file


def _relative_timestamp(iso_ts):
    """Convert ISO timestamp to relative format like '2m ago', '3h ago', '5d ago'."""
    try:
        dt = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        now = datetime.datetime.now(datetime.timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 0:
            return iso_ts
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        VMN_LOGGER.debug("Failed to parse timestamp %s", iso_ts, exc_info=True)
        return iso_ts


def _get_storage(vcs, params):
    return get_snapshot_storage(
        params.get("backend", "local"),
        vmn_root_path=vcs.vmn_root_path,
        bucket=params.get("bucket"),
        prefix=params.get("prefix", "vmn-snapshots"),
        endpoint_url=params.get("endpoint_url"),
    )


def _resolve_verstr(storage, app_name, verstr, latest=False, kind="snapshot"):
    """Resolve a version reference to a full verstr.

    Accepts: ``--latest`` / ``"latest"`` / ``"@latest"`` (most recent),
    ``"@N"`` (the N-th row shown by ``list``, 1-indexed, oldest-first), an exact
    verstr, a unique dev-verstr prefix, or a stamped (non-dev) version passed
    through untouched. Returns ``(resolved_verstr, error_message_or_None)``.
    """
    if latest or verstr in ("latest", "@latest"):
        snaps = storage.list_snapshots(app_name)
        if not snaps:
            return None, f"No {kind}s found for {app_name}"
        most_recent = max(snaps, key=lambda m: m.get("timestamp", ""))
        return most_recent["verstr"], None

    if verstr is None:
        return None, None

    # @N addresses the N-th row shown by `list` (1-indexed, oldest-first).
    if verstr.startswith("@"):
        idx_str = verstr[1:]
        if not idx_str.isdigit():
            return None, f"Invalid index reference '{verstr}' (use @N, e.g. @1)"
        n = int(idx_str)
        snaps = storage.list_snapshots(app_name)
        if n < 1 or n > len(snaps):
            return None, f"Index '{verstr}' out of range (1..{len(snaps)})"
        return snaps[n - 1]["verstr"], None

    # Try exact match first (fast path — no need to load full data)
    if storage.exists(app_name, verstr):
        return verstr, None

    # Stamped (non-dev) versions are not stored as snapshots but are
    # synthesized on-demand by _load_or_synthesize(). Pass them through.
    if "-dev." not in verstr:
        return verstr, None

    # Try prefix match: names are enough, no metadata needs parsing.
    if hasattr(storage, "list_verstrs"):
        names = storage.list_verstrs(app_name)
    else:
        names = [m["verstr"] for m in storage.list_snapshots(app_name)]
    matches = sorted(v for v in names if v.startswith(verstr))
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        cands = ", ".join(matches)
        return None, (
            f"Ambiguous prefix '{verstr}': matches {len(matches)} {kind}s: {cands}"
        )
    return None, f"{kind.capitalize()} '{verstr}' not found"


def _ensure_trailing_newline(s):
    """git apply/am require patches to end with a newline."""
    return s if s.endswith("\n") else s + "\n"


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
        wt_diff = backend._be.git.diff("HEAD")
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
        # The dev verstr always hashes stable untracked *content* (never the
        # tarball, whose gzip/tar headers embed mtimes), so `show --dev` and
        # `snapshot create` agree. The tarball is storage payload only.
        content_hash = _hash_untracked_content(backend.repo_path)
        if content_hash:
            patches["untracked_hash"] = content_hash
        if not lightweight:
            patches.update(untracked_payload(backend.repo_path))
    except Exception:
        VMN_LOGGER.debug("Failed to collect untracked files", exc_info=True)

    return patches


def untracked_payload(repo_path):
    """The stored untracked part of a snapshot: the tarball and what it skipped."""
    payload = {}
    untracked_tar, skipped = _collect_untracked_tarball(repo_path)
    if untracked_tar:
        payload["untracked_files"] = untracked_tar
    if skipped:
        payload["untracked_skipped"] = skipped
    return payload


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


_UNTRACKED_CACHE_FILE = "untracked_hash.cache"


def _load_untracked_cache(repo_path):
    """Load the (path,size,mtime)->content-sha cache for untracked files."""
    cache_path = os.path.join(repo_path, ".vmn", _UNTRACKED_CACHE_FILE)
    try:
        with open(cache_path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _store_untracked_cache(repo_path, cache):
    """Persist the untracked content-hash cache (best effort)."""
    vmn_dir = os.path.join(repo_path, ".vmn")
    if not os.path.isdir(vmn_dir):
        return
    try:
        # Atomic: concurrent sweep workers capture outside the repo lock.
        atomic_write(os.path.join(vmn_dir, _UNTRACKED_CACHE_FILE), json.dumps(cache))
    except OSError:
        VMN_LOGGER.debug("Failed to persist untracked hash cache", exc_info=True)


def _hash_untracked_content(repo_path):
    """Hash untracked non-ignored files by their content, deterministically.

    Returns a bytes digest over sorted ``(rel_path, content-sha256)`` pairs, or
    None if there are no untracked files. Per-file content hashes are cached by
    ``(size, mtime_ns)`` at ``.vmn/untracked_hash.cache`` so repeat calls (e.g.
    ``show --dev``) stay fast without re-reading unchanged files.
    """
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None

    cache = _load_untracked_cache(repo_path)
    new_cache = {}
    h = hashlib.sha256()
    file_count = 0
    for rel_path in sorted(result.stdout.strip().split("\n")):
        if not rel_path:
            continue
        if rel_path.startswith(".vmn/") or rel_path == ".vmn":
            continue
        abs_path = os.path.join(repo_path, rel_path)
        try:
            st = os.stat(abs_path)
            if not stat_module.S_ISREG(st.st_mode):
                continue
        except OSError:
            continue

        cached = cache.get(rel_path)
        if cached and cached[0] == st.st_size and cached[1] == st.st_mtime_ns:
            content_sha = cached[2]
        else:
            content_sha = _sha256_file(abs_path)
        new_cache[rel_path] = [st.st_size, st.st_mtime_ns, content_sha]
        h.update(f"{rel_path}\0{content_sha}\n".encode())
        file_count += 1

    if file_count == 0:
        return None

    _store_untracked_cache(repo_path, new_cache)
    return h.digest()


def _fmt_size(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.0f}{unit}" if unit == "B" else f"{nbytes:.1f}{unit}"
        nbytes /= 1024
    return f"{nbytes:.1f}TB"


_DEFAULT_MAX_FILE_MB = 50
_DEFAULT_MAX_TOTAL_MB = 200


def _mb_from_env(name, default_mb):
    raw = os.environ.get(name)
    try:
        mb = float(raw) if raw else default_mb
    except ValueError:
        VMN_LOGGER.warning(f"Ignoring invalid {name}={raw!r}")
        mb = default_mb
    return int(mb * 1024 * 1024)


def _untracked_caps():
    """``(per_file, total)`` byte caps on what the untracked tarball may hold."""
    return (
        _mb_from_env("VMN_SNAPSHOT_MAX_FILE_MB", _DEFAULT_MAX_FILE_MB),
        _mb_from_env("VMN_SNAPSHOT_MAX_TOTAL_MB", _DEFAULT_MAX_TOTAL_MB),
    )


def _untracked_candidates(repo_path):
    """``[(rel_path, abs_path, size)]`` of untracked, non-ignored regular files."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        return []

    candidates = []
    for rel_path in result.stdout.strip().split("\n"):
        if not rel_path or rel_path.startswith(".vmn/") or rel_path == ".vmn":
            continue
        abs_path = os.path.join(repo_path, rel_path)
        if os.path.isfile(abs_path):
            candidates.append((rel_path, abs_path, os.path.getsize(abs_path)))
    return candidates


def _within_caps(candidates):
    """Split candidates into (kept, skipped_rel_paths) under the size caps."""
    max_file, max_total = _untracked_caps()
    kept, skipped, budget = [], [], max_total
    for rel_path, abs_path, size in candidates:
        if size > max_file or size > budget:
            skipped.append(rel_path)
            continue
        kept.append((rel_path, abs_path, size))
        budget -= size
    if skipped:
        VMN_LOGGER.warning(
            "Not capturing %d untracked file(s) over the snapshot size caps "
            "(%s per file, %s total; see VMN_SNAPSHOT_MAX_FILE_MB / "
            "VMN_SNAPSHOT_MAX_TOTAL_MB): %s",
            len(skipped),
            _fmt_size(max_file),
            _fmt_size(max_total),
            ", ".join(skipped),
        )
    return kept, skipped


def _collect_untracked_tarball(repo_path):
    """Collect untracked non-ignored files into a tar.gz, within the size caps.

    Returns ``(tarball_bytes_or_None, skipped_rel_paths)``. The archive is built
    in a temporary file so only the finished tarball is ever held in memory.
    """
    kept, skipped = _within_caps(_untracked_candidates(repo_path))
    if not kept:
        return None, skipped

    total = len(kept)
    collected_bytes = 0
    with tempfile.TemporaryFile() as buf:
        with tarfile.open(mode="w:gz", fileobj=buf) as tar:
            for file_count, (rel_path, abs_path, size) in enumerate(kept, 1):
                tar.add(abs_path, arcname=rel_path)
                collected_bytes += size
                if file_count % 50 == 0:
                    VMN_LOGGER.info(
                        "Collecting untracked files: %d/%d (%s)",
                        file_count,
                        total,
                        _fmt_size(collected_bytes),
                    )
        VMN_LOGGER.info(
            "Collected %d untracked files (%s)", total, _fmt_size(collected_bytes)
        )
        buf.seek(0)
        return buf.read(), skipped


def _extract_untracked_tarball(dest, tarball_bytes):
    """Extract untracked files tarball into dest directory."""
    buf = io.BytesIO(tarball_bytes)
    with tarfile.open(mode="r:gz", fileobj=buf) as tar:
        tar.extractall(path=dest)


def _list_tarball_members(tarball_bytes):
    """List file names in a tarball."""
    buf = io.BytesIO(tarball_bytes)
    with tarfile.open(mode="r:gz", fileobj=buf) as tar:
        return sorted(m.name for m in tar.getmembers())


def _compute_verstr(base_version, commit_hash, patches, hash_len=7):
    return _format_dev_verstr(
        base_version, commit_hash, _compute_diff_hash(patches), hash_len
    )


def _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len=7):
    diff_part = diff_hash[:hash_len] if diff_hash else "0000000"
    return f"{base_version}-dev.{commit_hash[:7]}.{diff_part}"


# Diff-hash prefix lengths tried, shortest first, when a verstr is taken by a
# snapshot with different content (a 7-hex prefix is only 28 bits).
_DIFF_HASH_LENGTHS = (7, 12, 16, 24, 32, 64)


def _stored_diff_hash(storage, app_name, verstr):
    """``(exists, diff_hash)`` of the snapshot stored at *verstr*."""
    raw = storage.load_file(app_name, verstr, "metadata.yml")
    if raw is None:
        return False, None
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError:
        meta = None
    return True, meta.get("diff_hash") if isinstance(meta, dict) else None


def _unique_snapshot_verstr(storage, app_name, base_version, commit_hash, diff_hash):
    """The shortest dev verstr that is free or already holds this exact content.

    A snapshot never overwrites a different one: on a prefix collision (or a
    legacy record that carries no ``diff_hash`` to compare) the diff hash is
    extended instead.
    """
    verstr = _format_dev_verstr(base_version, commit_hash, diff_hash)
    if not diff_hash:
        return verstr
    for hash_len in _DIFF_HASH_LENGTHS:
        verstr = _format_dev_verstr(base_version, commit_hash, diff_hash, hash_len)
        exists, stored = _stored_diff_hash(storage, app_name, verstr)
        if not exists or stored == diff_hash:
            return verstr
    return verstr


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


def _apply_snapshot_patches(vcs, params, metadata, patches):
    """Apply snapshot patches to restore a dev version state."""
    base_commit = metadata["base_commit"]

    if not params.get("deps_only"):
        try:
            vcs.backend.checkout(rev=base_commit)
        except Exception:
            VMN_LOGGER.error(f"Failed to checkout base commit {base_commit[:7]}")
            VMN_LOGGER.debug("Logged Exception message:", exc_info=True)
            return 1

        if patches.get("local_commits"):
            result = subprocess.run(
                ["git", "am", "--3way"],
                input=_ensure_trailing_newline(patches["local_commits"]),
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(
                    f"Failed to apply local commits patch: {result.stderr}"
                )
                return 1

        if patches.get("working_tree"):
            result = subprocess.run(
                ["git", "apply", "--3way"],
                input=_ensure_trailing_newline(patches["working_tree"]),
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            if result.returncode != 0:
                VMN_LOGGER.error(f"Failed to apply working tree patch: {result.stderr}")
                return 1

        if patches.get("untracked_files"):
            try:
                _extract_untracked_tarball(
                    vcs.vmn_root_path, patches["untracked_files"]
                )
            except Exception:
                VMN_LOGGER.warning("Failed to extract untracked files from snapshot")
                VMN_LOGGER.debug("Logged Exception message:", exc_info=True)

    _apply_dep_patches(vcs, metadata, patches)

    VMN_LOGGER.info(f"Restored dev version {metadata['verstr']} of {vcs.name}")
    return 0


def _apply_dep_patches(vcs, metadata, patches):
    dep_patches = patches.get("deps", {})
    if not dep_patches:
        return

    changesets = metadata.get("changesets", {})
    for dep_name, dp in dep_patches.items():
        dep_info = None
        for cs_path, cs_info in changesets.items():
            safe = cs_path.replace(os.sep, "_").replace("/", "_")
            if safe == dep_name or cs_path == dep_name:
                dep_info = cs_info
                dep_path = cs_path
                break

        if not dep_info:
            VMN_LOGGER.warning(
                f"No changeset info for dep {dep_name}, skipping patches"
            )
            continue

        full_path = os.path.join(vcs.vmn_root_path, dep_path)
        if not os.path.isdir(full_path):
            VMN_LOGGER.warning(f"Dep directory {dep_path} not found, skipping patches")
            continue

        dep_hash = dep_info.get("hash")
        if dep_hash:
            try:
                result = subprocess.run(
                    ["git", "checkout", dep_hash],
                    capture_output=True,
                    text=True,
                    cwd=full_path,
                )
                if result.returncode != 0:
                    VMN_LOGGER.warning(
                        f"Failed to checkout dep {dep_path} at {dep_hash[:7]}"
                    )
            except Exception:
                VMN_LOGGER.debug(f"Failed to checkout dep {dep_path}", exc_info=True)

        _apply_patches_to_workdir(full_path, dp)


def _parse_meta_args(meta_list):
    """Parse ['key=val', ...] into a dict."""
    if not meta_list:
        return {}
    result = {}
    for item in meta_list:
        if "=" not in item:
            VMN_LOGGER.error(f"Invalid --meta format: {item}. Expected key=value")
            raise ValueError(f"Invalid meta format: {item}")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _build_user_meta(meta_args, meta_file):
    """Build user_meta dict from CLI --meta args and/or --meta-file."""
    result = {}
    if meta_file:
        with open(meta_file) as f:
            file_meta = yaml.safe_load(f)
        if isinstance(file_meta, dict):
            result.update(file_meta)
        else:
            VMN_LOGGER.error(
                f"--meta-file must contain a YAML mapping, got {type(file_meta).__name__}"
            )
            raise ValueError("Invalid meta file format")
    if meta_args:
        result.update(_parse_meta_args(meta_args))
    return result or None


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
    commit_hash = be.changeset()

    patches = _generate_patches(be, lightweight=lightweight)
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


def _skipped_untracked(patches):
    """Untracked paths left out by the size caps, deps prefixed by their path."""
    skipped = list(patches.get("untracked_skipped", []))
    for dep_path, dp in sorted(patches.get("deps", {}).items()):
        skipped.extend(f"{dep_path}/{p}" for p in dp.get("untracked_skipped", []))
    return skipped


def _build_snapshot_metadata(
    vcs,
    verstr,
    base_version,
    commit_hash,
    dirty_states,
    patches,
    ver_info,
    note=None,
    user_meta=None,
):
    be = vcs.backend
    try:
        remote_url = be.remote()
    except Exception:
        remote_url = None

    metadata = {
        "verstr": verstr,
        "base_version": base_version,
        "base_commit": commit_hash,
        "branch": be.active_branch,
        "remote": remote_url,
        "timestamp": _now_iso(),
        "note": note,
        "app_name": vcs.name,
        "dirty_states": dirty_states,
        "has_working_tree_patch": "working_tree" in patches,
        "has_local_commits_patch": "local_commits" in patches,
        "has_untracked_files": "untracked_files" in patches,
        "has_dep_patches": bool(patches.get("deps")),
    }
    diff_hash = _compute_diff_hash(patches)
    if diff_hash:
        metadata["diff_hash"] = diff_hash
    skipped = _skipped_untracked(patches)
    if skipped:
        metadata["untracked_skipped"] = skipped
    if user_meta:
        metadata["user_meta"] = user_meta

    changesets = ver_info["stamping"]["app"].get("changesets", {})
    if changesets:
        metadata["changesets"] = changesets
    return metadata


@measure_runtime_decorator
def snapshot_create(vcs, params, note=None, user_meta=None):
    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs)
    if err is not None:
        return err

    storage = _get_storage(vcs, params)
    verstr = _unique_snapshot_verstr(
        storage, vcs.name, base_version, commit_hash, _compute_diff_hash(patches)
    )
    metadata = _build_snapshot_metadata(
        vcs,
        verstr,
        base_version,
        commit_hash,
        dirty_states,
        patches,
        ver_info,
        note=note,
        user_meta=user_meta,
    )
    storage.save(vcs.name, verstr, metadata, patches)

    VMN_LOGGER.info(f"Created snapshot: {verstr}")
    print(verstr)
    return 0


def _save_safety_snapshot(vcs, params, target_verstr):
    """Snapshot the current dirty state before a restore overwrites it.

    Returns the saved verstr, or None when the tree is clean or already equals
    the restore target (nothing to lose).
    """
    (
        base_version,
        commit_hash,
        patches,
        dirty_states,
        ver_info,
        err,
    ) = gather_create_data(vcs)
    if err is not None:
        return None  # clean tree (err==0) or a real error — nothing to save

    storage = _get_storage(vcs, params)
    verstr = _unique_snapshot_verstr(
        storage, vcs.name, base_version, commit_hash, _compute_diff_hash(patches)
    )
    if verstr == target_verstr:
        return None

    metadata = _build_snapshot_metadata(
        vcs,
        verstr,
        base_version,
        commit_hash,
        dirty_states,
        patches,
        ver_info,
        note="auto-saved before restore",
    )
    storage.save(vcs.name, verstr, metadata, patches)
    return verstr


def _reset_worktree(vcs):
    """Discard tracked + untracked working-tree changes (keeps .vmn/ ignored data)."""
    for cmd in (["git", "reset", "--hard"], ["git", "clean", "-fd"]):
        result = subprocess.run(cmd, cwd=vcs.vmn_root_path, capture_output=True)
        if result.returncode != 0:
            stderr = (
                result.stderr.decode().strip() if result.stderr else "unknown error"
            )
            raise RuntimeError(
                f"Failed to reset working tree ({' '.join(cmd)}): {stderr}"
            )


def _restore_with_safety_net(vcs, params, metadata, patches):
    """Apply a restore, first auto-snapshotting any dirty work it would clobber.

    The current dirty state is preserved as a snapshot, then the working tree is
    cleared so the target state applies cleanly.
    """
    saved = _save_safety_snapshot(vcs, params, metadata.get("verstr"))
    if saved:
        VMN_LOGGER.info(
            f"Current work saved as {saved} — restore it anytime with: "
            f"vmn snapshot restore {vcs.name} -v {saved}"
        )
    if not params.get("deps_only"):
        _reset_worktree(vcs)
    return _apply_snapshot_patches(vcs, params, metadata, patches)


@measure_runtime_decorator
def snapshot_restore(vcs, params, verstr):
    storage = _get_storage(vcs, params)
    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
    ret = _restore_with_safety_net(vcs, params, metadata, patches)
    if ret == 0:
        VMN_LOGGER.info(f"Restored snapshot {verstr}")
    return ret


@measure_runtime_decorator
def snapshot_list(vcs, params):
    storage = _get_storage(vcs, params)
    snapshots = storage.list_snapshots(vcs.name)
    if not snapshots:
        VMN_LOGGER.info(f"No snapshots found for {vcs.name}")
        return 0

    # Numbers are the storage index `@N` resolves, fixed before --last/--filter.
    numbered = list(enumerate(snapshots, 1))
    last = params.get("last")
    if last:
        numbered = numbered[-last:]

    filters = _parse_meta_args(params.get("filter")) if params.get("filter") else None

    for idx, meta in numbered:
        if filters:
            user_meta = meta.get("user_meta", {})
            if not all(str(user_meta.get(k)) == v for k, v in filters.items()):
                continue

        if params.get("verbose"):
            ts_display = meta["timestamp"]
        else:
            ts_display = _relative_timestamp(meta["timestamp"])
        note_str = f" - {meta['note']}" if meta.get("note") else ""
        meta_str = ""
        if meta.get("user_meta"):
            meta_str = " " + " ".join(f"{k}={v}" for k, v in meta["user_meta"].items())
        print(f"[{idx}] {meta['verstr']}  ({ts_display}){note_str}{meta_str}")

    return 0


@measure_runtime_decorator
def snapshot_show(vcs, params, verstr):
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1

    storage = _get_storage(vcs, params)

    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1

    print(yaml.dump(metadata, sort_keys=True))
    if patches.get("working_tree"):
        print("--- Working tree patch ---")
        print(patches["working_tree"])
    if patches.get("local_commits"):
        print("--- Local commits patch ---")
        print(patches["local_commits"])
    if patches.get("untracked_files"):
        print("--- Untracked files ---")
        for name in _list_tarball_members(patches["untracked_files"]):
            print(f"  {name}")

    if patches.get("deps"):
        for dep_name, dp in patches["deps"].items():
            print(f"\n--- Dep: {dep_name} ---")
            if dp.get("working_tree"):
                print(f"  working tree patch: {len(dp['working_tree'])} bytes")
            if dp.get("local_commits"):
                print(f"  local commits patch: {len(dp['local_commits'])} bytes")
            if dp.get("untracked_files"):
                print(
                    f"  untracked files: {len(_list_tarball_members(dp['untracked_files']))} files"
                )

    return 0


@measure_runtime_decorator
def snapshot_note(vcs, params, verstr, note):
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1
    if note is None:
        VMN_LOGGER.error("Must specify --note")
        return 1

    storage = _get_storage(vcs, params)

    if storage.update_note(vcs.name, verstr, note):
        VMN_LOGGER.info(f"Updated note for {verstr}")
        return 0
    else:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1


def _synthesize_stamped_version(vcs, verstr):
    """Synthesize empty snapshot metadata for a stamped (non-dev) version.

    A stamped version is a clean checkout at a tag — no patches.
    Returns (metadata, patches) or (None, None) if not resolvable.
    """
    if "-dev." in verstr:
        return None, None

    try:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(verstr)
    except Exception:
        VMN_LOGGER.debug(f"Failed to resolve stamped version {verstr}", exc_info=True)
        return None, None

    if tag_name not in ver_infos or ver_infos[tag_name]["ver_info"] is None:
        return None, None

    ver_info = ver_infos[tag_name]["ver_info"]
    changesets = ver_info["stamping"]["app"].get("changesets", {})
    commit_hash = changesets.get(".", {}).get("hash", "")
    if not commit_hash:
        return None, None

    metadata = {
        "verstr": verstr,
        "base_version": verstr,
        "base_commit": commit_hash,
        "branch": changesets.get(".", {}).get("branch", ""),
        "remote": changesets.get(".", {}).get("remote", ""),
        "timestamp": "stamped",
        "note": None,
        "app_name": vcs.name,
        "changesets": changesets,
    }
    return metadata, {}


def _load_or_synthesize(storage, vcs, verstr):
    """Load a snapshot from storage, or synthesize for stamped versions."""
    meta, patches = storage.load(vcs.name, verstr)
    if meta is not None:
        return meta, patches

    # Not in storage — try to resolve as a stamped version
    meta, patches = _synthesize_stamped_version(vcs, verstr)
    if meta is not None:
        return meta, patches

    return None, None


@measure_runtime_decorator
def snapshot_diff(vcs, params, verstr1, verstr2, tool=None):
    """Compare two snapshots. verstr2 can be 'current' to diff against working state."""
    if verstr1 is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1
    if verstr2 is None:
        VMN_LOGGER.error("Must specify --to version (or 'current')")
        return 1

    storage = _get_storage(vcs, params)

    meta1, patches1 = _load_or_synthesize(storage, vcs, verstr1)
    if meta1 is None:
        VMN_LOGGER.error(f"Snapshot {verstr1} not found")
        return 1

    if verstr2 == "current":
        patches2 = _generate_patches(vcs.backend)
        meta2 = {
            "verstr": "current",
            "timestamp": "now",
            "branch": vcs.backend.active_branch,
        }
    else:
        meta2, patches2 = _load_or_synthesize(storage, vcs, verstr2)
        if meta2 is None:
            VMN_LOGGER.error(f"Snapshot {verstr2} not found")
            return 1

    tool = tool or get_git_difftool(vcs)

    if tool:
        return _diff_with_external_tool(
            tool, vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
        )
    return _diff_real_tree(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2)


def _materialize_for_diff(vcs, verstr, meta, patches, dest):
    """Materialize a snapshot/experiment into ``dest`` (no .git, no vmn metadata)
    for diffing. 'current'/base-less meta materializes the live HEAD.
    """
    m = dict(meta)
    if not m.get("base_commit"):
        m["base_commit"] = vcs.backend.changeset()
    if _materialize_workdir(vcs, m, patches, dest) != 0:
        return False
    _strip_git_dirs(dest)
    # vmn's own export metadata is not part of the user's code.
    try:
        os.remove(os.path.join(dest, "vmn_metadata.yml"))
    except OSError:
        pass
    return True


def render_tree_diff(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Real file-level diff text between two materialized snapshot workdirs.

    Returns (diff_text, error_message_or_None); empty text means identical.
    """
    parent = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        name1 = verstr1.replace("+", "_plus_")
        name2 = verstr2.replace("+", "_plus_")
        if name1 == name2:
            name2 += "_b"
        ok1 = _materialize_for_diff(
            vcs, verstr1, meta1, patches1, os.path.join(parent, name1)
        )
        ok2 = _materialize_for_diff(
            vcs, verstr2, meta2, patches2, os.path.join(parent, name2)
        )
        if not ok1 or not ok2:
            return None, "Failed to materialize snapshots for diff"
        # Run with cwd=parent so git labels the sides by their version strings.
        result = subprocess.run(
            ["git", "diff", "--no-index", "--", name1, name2],
            capture_output=True,
            text=True,
            cwd=parent,
        )
        return result.stdout, None
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _diff_real_tree(vcs, verstr1, meta1, patches1, verstr2, meta2, patches2):
    """Print a real file-level diff between two materialized snapshot workdirs."""
    text, err = render_tree_diff(
        vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
    )
    if err:
        VMN_LOGGER.error(err)
        return 1
    if text.strip():
        print(text, end="" if text.endswith("\n") else "\n")
    else:
        print(f"{verstr1} and {verstr2} are identical")
    return 0


def get_git_difftool(vcs):
    try:
        return vcs.backend._be.git.config("diff.tool")
    except Exception:
        return None


def _diff_with_external_tool(
    tool, vcs, verstr1, meta1, patches1, verstr2, meta2, patches2
):
    """Materialize both snapshots as workdirs and launch external diff tool."""
    tmpdir = tempfile.mkdtemp(prefix="vmn-diff-")
    try:
        left_dir = os.path.join(tmpdir, verstr1.replace("+", "_plus_"))
        right_dir = os.path.join(tmpdir, verstr2.replace("+", "_plus_"))

        left_ok = _materialize_workdir(vcs, meta1, patches1, left_dir) == 0
        right_ok = _materialize_workdir(vcs, meta2, patches2, right_dir) == 0

        if not left_ok or not right_ok:
            # Fallback: write patches to dirs
            if not left_ok:
                os.makedirs(left_dir, exist_ok=True)
                _write_snapshot_to_dir(left_dir, meta1, patches1)
            if not right_ok:
                os.makedirs(right_dir, exist_ok=True)
                _write_snapshot_to_dir(right_dir, meta2, patches2)

        result = subprocess.run([tool, left_dir, right_dir])
        return result.returncode
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _write_snapshot_to_dir(directory, metadata, patches):
    """Write snapshot metadata and patches to a directory (fallback)."""
    with open(os.path.join(directory, "metadata.yml"), "w") as f:
        yaml.dump(metadata, f, sort_keys=True)
    if patches.get("working_tree"):
        with open(os.path.join(directory, "working_tree.patch"), "w") as f:
            f.write(patches["working_tree"])
    if patches.get("local_commits"):
        with open(os.path.join(directory, "local_commits.patch"), "w") as f:
            f.write(patches["local_commits"])
    if patches.get("untracked_files"):
        with open(os.path.join(directory, "untracked_files.tar.gz"), "wb") as f:
            f.write(patches["untracked_files"])


# Seconds a git subprocess may take while materializing a snapshot: local
# operations are quick, network ones must not hang an export or a ui diff.
_LOCAL_GIT_TIMEOUT_SEC = 120
_NETWORK_GIT_TIMEOUT_SEC = 300


def _git(args, cwd=None, timeout=_LOCAL_GIT_TIMEOUT_SEC):
    """Run git; a CompletedProcess, or None when it timed out."""
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        VMN_LOGGER.error(f"git {' '.join(args[:2])} timed out after {timeout}s")
        return None


def _git_ok(args, cwd=None, timeout=_LOCAL_GIT_TIMEOUT_SEC, what=None):
    result = _git(args, cwd=cwd, timeout=timeout)
    if result is not None and result.returncode == 0:
        return True
    if what and result is not None:
        VMN_LOGGER.error(f"{what} failed: {result.stderr}")
    return False


def _commit_exists(repo_path, commit_hash):
    """Whether *commit_hash* is in the local repository at *repo_path*."""
    if not repo_path or not commit_hash or not os.path.isdir(repo_path):
        return False
    return _git_ok(["cat-file", "-e", f"{commit_hash}^{{commit}}"], cwd=repo_path)


def _clone_local_at(dest, repo_path, commit_hash):
    """Check *commit_hash* out of a local repository — no network involved.

    ``--shared`` borrows the source's object store, so even a commit no ref
    points at (a detached or rebased-away base) checks out.
    """
    if not _git_ok(
        ["clone", "--shared", "--no-checkout", "--quiet", repo_path, dest],
        what="git clone (local)",
    ):
        return 1
    if not _git_ok(
        ["checkout", "--quiet", commit_hash],
        cwd=dest,
        what=f"git checkout {commit_hash[:7]}",
    ):
        return 1
    return 0


def _clone_at(dest, local_repo, remote, commit_hash):
    """Materialize *commit_hash* from the local repo when it has it, else remote."""
    if _commit_exists(local_repo, commit_hash):
        return _clone_local_at(dest, local_repo, commit_hash)
    return _shallow_clone_at(dest, remote, commit_hash)


def _shallow_clone_at(dest, remote, commit_hash):
    """Create a shallow clone at a specific commit."""
    # Try shallow fetch first (works with servers that support it)
    os.makedirs(dest, exist_ok=True)
    if not _git_ok(["init"], cwd=dest, what=f"git init in {dest}"):
        return 1

    if _git_ok(
        ["fetch", "--depth", "1", remote, commit_hash],
        cwd=dest,
        timeout=_NETWORK_GIT_TIMEOUT_SEC,
    ) and _git_ok(["checkout", "FETCH_HEAD"], cwd=dest):
        return 0

    # Fallback: full clone + checkout (for local repos / servers without SHA1 fetch)
    VMN_LOGGER.warning(
        f"Shallow fetch failed for {commit_hash[:7]}, falling back to full clone"
    )
    shutil.rmtree(dest, ignore_errors=True)
    if not _git_ok(
        ["clone", "--no-checkout", remote, dest],
        timeout=_NETWORK_GIT_TIMEOUT_SEC,
        what="git clone",
    ):
        return 1

    if not _git_ok(
        ["checkout", commit_hash], cwd=dest, what=f"git checkout {commit_hash[:7]}"
    ):
        return 1

    return 0


def _apply_patches_to_workdir(dest, patches):
    """Apply local_commits and working_tree patches to a workdir."""
    if patches.get("local_commits"):
        result = subprocess.run(
            ["git", "am", "--3way"],
            input=_ensure_trailing_newline(patches["local_commits"]),
            capture_output=True,
            text=True,
            cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply local commits: {result.stderr}")

    if patches.get("working_tree"):
        result = subprocess.run(
            ["git", "apply"],
            input=_ensure_trailing_newline(patches["working_tree"]),
            capture_output=True,
            text=True,
            cwd=dest,
        )
        if result.returncode != 0:
            VMN_LOGGER.warning(f"Failed to apply working tree patch: {result.stderr}")

    if patches.get("untracked_files"):
        try:
            _extract_untracked_tarball(dest, patches["untracked_files"])
        except Exception:
            VMN_LOGGER.debug(
                "Failed to extract untracked files in workdir", exc_info=True
            )


def _copy_untracked_files(repo_path, dest):
    """Copy untracked non-ignored files from repo to dest."""
    result = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        return

    for rel_path in result.stdout.strip().split("\n"):
        if not rel_path:
            continue
        src = os.path.join(repo_path, rel_path)
        dst = os.path.join(dest, rel_path)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


def _resolve_remote(remote, vcs):
    """Resolve a remote URL, converting relative paths to absolute."""
    if not remote:
        return remote
    vmn_root = vcs.vmn_root_path if vcs and hasattr(vcs, "vmn_root_path") else None
    if vmn_root and not remote.startswith(
        ("http://", "https://", "git://", "ssh://", "git@")
    ):
        # Relative or local path — resolve against vmn_root
        resolved = os.path.normpath(os.path.join(vmn_root, remote))
        if os.path.exists(resolved):
            return resolved
    return remote


def _predates_untracked_capture(metadata):
    """A stored dev snapshot from before untracked files were captured."""
    return "has_untracked_files" not in metadata and "-dev." in str(
        metadata.get("verstr", "")
    )


def _materialize_workdir(vcs, metadata, patches, output_path):
    """Materialize a patch snapshot into a complete working directory."""
    base_commit = metadata.get("base_commit")
    remote = metadata.get("remote")

    if not base_commit:
        VMN_LOGGER.error("Snapshot metadata missing base_commit")
        return 1

    local_repo = getattr(vcs, "vmn_root_path", None) if vcs else None
    if not remote and not local_repo:
        VMN_LOGGER.error("Snapshot metadata missing remote URL")
        return 1

    # Local-first: the recorded remote is only consulted when the local
    # repository does not have the base commit (offline / air-gapped safe).
    err = _clone_at(
        output_path, local_repo, _resolve_remote(remote, vcs) or local_repo, base_commit
    )
    if err:
        return err

    _apply_patches_to_workdir(output_path, patches)

    # Snapshots taken before untracked files were captured carry no
    # ``has_untracked_files`` flag: for those only, fall back to the live
    # working tree's untracked files when HEAD matches the base commit. Every
    # other record says exactly what it holds, so nothing else is copied in.
    if _predates_untracked_capture(metadata) and local_repo:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=vcs.vmn_root_path,
            )
            current_head = result.stdout.strip()
            if current_head.startswith(base_commit[:7]) or base_commit.startswith(
                current_head[:7]
            ):
                _copy_untracked_files(vcs.vmn_root_path, output_path)
            else:
                VMN_LOGGER.debug(
                    f"HEAD ({current_head[:7]}) != base_commit ({base_commit[:7]}), "
                    "skipping untracked files"
                )
        except Exception:
            VMN_LOGGER.debug("Failed to copy untracked files", exc_info=True)

    # Export dependencies and apply dep patches
    changesets = metadata.get("changesets", {})
    dep_patches = patches.get("deps", {})
    for dep_path, dep_info in changesets.items():
        if dep_path == ".":
            continue

        dep_hash = dep_info.get("hash")
        dep_remote = dep_info.get("remote")
        if not dep_hash or not dep_remote:
            VMN_LOGGER.warning(
                f"Dependency {dep_path} missing hash or remote, skipping"
            )
            continue

        dep_remote = _resolve_remote(dep_remote, vcs)
        dep_local = os.path.join(local_repo, dep_path) if local_repo else None

        dep_dest = os.path.join(output_path, dep_path)
        err = _clone_at(dep_dest, dep_local, dep_remote, dep_hash)
        if err:
            VMN_LOGGER.warning(f"Failed to export dependency {dep_path}")
            continue

        safe_dep = dep_path.replace(os.sep, "_").replace("/", "_")
        dp = dep_patches.get(safe_dep) or dep_patches.get(dep_path)
        if dp:
            _apply_patches_to_workdir(dep_dest, dp)

    # Write metadata
    meta_path = os.path.join(output_path, "vmn_metadata.yml")
    with open(meta_path, "w") as f:
        yaml.dump(metadata, f, sort_keys=True)

    return 0


def _strip_git_dirs(root_path):
    """Remove all .git directories to make export fully offline."""
    for dirpath, dirnames, _ in os.walk(root_path, topdown=True):
        if ".git" in dirnames:
            shutil.rmtree(os.path.join(dirpath, ".git"), ignore_errors=True)
            dirnames.remove(".git")


@measure_runtime_decorator
def snapshot_export(vcs, params, verstr, output_path):
    """Export a snapshot as a complete working directory or tarball."""
    if verstr is None:
        VMN_LOGGER.error("Must specify version with -v")
        return 1

    storage = _get_storage(vcs, params)
    metadata, patches = storage.load(vcs.name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1

    safe_verstr = verstr.replace("+", "_plus_")
    if output_path is None:
        output_path = safe_verstr

    is_tarball = output_path.endswith(".tar.gz") or output_path.endswith(".tgz")

    if is_tarball:
        tmpdir = tempfile.mkdtemp(prefix="vmn-export-")
        dest = os.path.join(tmpdir, safe_verstr)
    else:
        tmpdir = None
        dest = output_path

    try:
        err = _materialize_workdir(vcs, metadata, patches, dest)
        if err:
            return err

        _strip_git_dirs(dest)

        if is_tarball:
            with tarfile.open(output_path, "w:gz") as tar:
                tar.add(dest, arcname=safe_verstr)

        VMN_LOGGER.info(f"Exported snapshot to {output_path}")
        print(output_path)
        return 0
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)

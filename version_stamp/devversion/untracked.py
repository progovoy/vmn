"""Untracked-file payload helpers for dev-version capture."""
import hashlib
import io
import json
import os
import stat as stat_module
import subprocess
import tarfile
import tempfile

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.core.utils import sha256_file

_sha256_file = sha256_file

_UNTRACKED_CACHE_FILE = "untracked_hash.cache"
_DEFAULT_MAX_FILE_MB = 50
_DEFAULT_MAX_TOTAL_MB = 200


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
    path = os.path.join(vmn_dir, _UNTRACKED_CACHE_FILE)
    data = json.dumps(cache)
    try:
        fd, tmp = tempfile.mkstemp(dir=vmn_dir, prefix=".cache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
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


def untracked_payload(repo_path):
    """The stored untracked part of a snapshot: the tarball and what it skipped."""
    payload = {}
    untracked_tar, skipped = _collect_untracked_tarball(repo_path)
    if untracked_tar:
        payload["untracked_files"] = untracked_tar
    if skipped:
        payload["untracked_skipped"] = skipped
    return payload


def copy_untracked_files(repo_path, dest):
    """Copy untracked non-ignored files (never .vmn/) from repo to dest."""
    import shutil

    for rel_path, abs_path, _ in _untracked_candidates(repo_path):
        dst = os.path.join(dest, rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(abs_path, dst)

"""Resolve a user's snapshot/experiment reference to a stored verstr.

:func:`resolve_with` is the one dispatcher (``latest`` / ``@N`` / exact /
prefix) and owns the error messages; each backend — a storage walk
(:func:`_resolve_verstr`), an index snapshot, the persisted index's SQL —
passes its own :class:`RefLookups`.
"""
from dataclasses import dataclass
from typing import Callable

RUN_NOT_FOUND = "run_not_found"  # no such verstr/prefix, @N out of range, no runs
AMBIGUOUS_REF = "ambiguous_ref"  # a prefix matching several runs
INVALID_REF = "invalid_ref"  # a malformed ref

LATEST_WORDS = ("latest", "@latest")


class RefError(str):
    """A resolution error: its message, with the reason as ``code``."""

    def __new__(cls, message, code=RUN_NOT_FOUND):
        error = super().__new__(cls, message)
        error.code = code
        return error


@dataclass(frozen=True)
class RefLookups:
    """What :func:`resolve_with` asks a backend."""

    latest: Callable  # () -> the most recent verstr, or None without runs
    at: Callable  # (n >= 1) -> the n-th verstr in storage order, or None
    count: Callable  # () -> how many runs there are
    exists: Callable  # (verstr) -> bool
    with_prefix: Callable  # (prefix) -> the sorted verstrs starting with it


def no_runs_error(kind, app_name):
    """What resolving ``latest`` answers for an app without runs."""
    return RefError(f"No {kind}s found for {app_name}")


def resolve_with(lookups, app_name, ref, latest=False, kind="snapshot"):
    """``(verstr, error)`` for *ref*: ``latest``/``@latest`` (or *latest*),
    ``@N`` (1-indexed storage order), an exact verstr, a unique dev-verstr
    prefix, or a stamped (non-dev) version passed through untouched."""
    if latest or ref in LATEST_WORDS:
        newest = lookups.latest()
        return (newest, None) if newest is not None else (None, no_runs_error(kind, app_name))
    if ref is None:
        return None, None
    if ref.startswith("@"):
        return _at_index(lookups, ref)
    if "-dev." not in ref or lookups.exists(ref):
        return ref, None
    return _by_prefix(lookups.with_prefix(ref), ref, kind)


def _at_index(lookups, ref):
    idx = ref[1:]
    if not idx.isdigit():
        return None, RefError(f"Invalid index reference '{ref}' (use @N, e.g. @1)", INVALID_REF)
    verstr = lookups.at(int(idx)) if int(idx) >= 1 else None
    if verstr is None:
        return None, RefError(f"Index '{ref}' out of range (1..{lookups.count()})")
    return verstr, None


def _by_prefix(matches, ref, kind):
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, RefError(
            f"Ambiguous prefix '{ref}': matches {len(matches)} {kind}s: " + ", ".join(matches),
            AMBIGUOUS_REF,
        )
    return None, RefError(f"{kind.capitalize()} '{ref}' not found")


def _resolve_verstr(storage, app_name, verstr, latest=False, kind="snapshot"):
    """Resolve a version reference to a full verstr by walking *storage*
    (see :func:`resolve_with`). Returns ``(resolved_verstr, error_or_None)``."""
    return resolve_with(_storage_lookups(storage, app_name), app_name, verstr, latest, kind)


def _storage_lookups(storage, app_name):
    listed = []

    def snaps():
        if not listed:
            listed.append(storage.list_snapshots(app_name))
        return listed[0]

    def latest():
        return max(snaps(), key=lambda m: m.get("timestamp", ""))["verstr"] if snaps() else None

    def names():
        if hasattr(storage, "list_verstrs"):
            return storage.list_verstrs(app_name)
        return [m["verstr"] for m in snaps()]

    return RefLookups(
        latest=latest,
        at=lambda n: snaps()[n - 1]["verstr"] if n <= len(snaps()) else None,
        count=lambda: len(snaps()),
        exists=lambda verstr: storage.exists(app_name, verstr),
        with_prefix=lambda prefix: sorted(v for v in names() if v.startswith(prefix)),
    )

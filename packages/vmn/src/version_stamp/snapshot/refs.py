"""Resolve a user's snapshot reference to a stored verstr.

``resolve_snapshot_ref(store, app_name, ref, latest=False, kind="snapshot")
-> (verstr | None, error | None)`` — a port of vmn-exp's
``vmn_exp.core.resolve_ref._resolve_verstr`` (same results and messages).
Accepts ``latest``/``@latest`` (or ``latest=True``), ``@N`` (1-indexed,
oldest first, as ``list`` numbers rows), an exact verstr, a unique dev-verstr
prefix, or a stamped version, passed through untouched.
"""


def _latest(store, app_name, kind):
    snaps = store.list_snapshots(app_name)
    if not snaps:
        return None, f"No {kind}s found for {app_name}"
    return max(snaps, key=lambda m: m.get("timestamp", ""))["verstr"], None


def _at_index(store, app_name, ref):
    if not ref[1:].isdigit():
        return None, f"Invalid index reference '{ref}' (use @N, e.g. @1)"
    n = int(ref[1:])
    snaps = store.list_snapshots(app_name)
    if n < 1 or n > len(snaps):
        return None, f"Index '{ref}' out of range (1..{len(snaps)})"
    return snaps[n - 1]["verstr"], None


def _by_prefix(store, app_name, ref, kind):
    matches = sorted(v for v in store.list_verstrs(app_name) if v.startswith(ref))
    if len(matches) == 1:
        return matches[0], None
    if matches:
        return None, (
            f"Ambiguous prefix '{ref}': matches {len(matches)} {kind}s: "
            f"{', '.join(matches)}"
        )
    return None, f"{kind.capitalize()} '{ref}' not found"


def resolve_snapshot_ref(store, app_name, ref, latest=False, kind="snapshot"):
    if latest or ref in ("latest", "@latest"):
        return _latest(store, app_name, kind)
    if ref is None:
        return None, None
    if ref.startswith("@"):
        return _at_index(store, app_name, ref)
    if store.exists(app_name, ref) or "-dev." not in ref:
        return ref, None
    return _by_prefix(store, app_name, ref, kind)

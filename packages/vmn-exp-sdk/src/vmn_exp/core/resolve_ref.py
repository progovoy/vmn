"""Resolve a user's snapshot/experiment reference to a stored verstr."""


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

    if verstr.startswith("@"):
        idx_str = verstr[1:]
        if not idx_str.isdigit():
            return None, f"Invalid index reference '{verstr}' (use @N, e.g. @1)"
        n = int(idx_str)
        snaps = storage.list_snapshots(app_name)
        if n < 1 or n > len(snaps):
            return None, f"Index '{verstr}' out of range (1..{len(snaps)})"
        return snaps[n - 1]["verstr"], None

    if storage.exists(app_name, verstr):
        return verstr, None

    if "-dev." not in verstr:
        return verstr, None

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

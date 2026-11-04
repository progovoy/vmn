#!/usr/bin/env python3
"""The guards of ``vmn-exp prune`` (see :mod:`vmn_exp.cli.prune`): which
candidates are tag-protected or registered, and how a skip reads."""
from vmn_exp.core.status import STUCK


def tag_protected(candidates, protect_tags):
    """``{verstr: matched tag name}`` of *candidates* carrying any of
    *protect_tags* — a run's own current tags, so a removed tag never
    protects it."""
    if not protect_tags:
        return {}
    protect = set(protect_tags)
    protected = {}
    for meta in candidates:
        hit = protect & set((meta.get("tags") or {}).keys())
        if hit:
            protected[meta["verstr"]] = sorted(hit)[0]
    return protected


def registry_protected(storage, app_name, candidates):
    """Return ``{verstr: reason}`` for candidates referenced by a non-deleted
    model version.  Never overridable by ``--force``.

    Raises any exception from the registry — callers must catch and fail closed.
    Only called when *storage* exposes ``list_record_names`` (the registry
    interface); storages without it are treated as having no registry.
    """
    if not candidates or not hasattr(storage, "list_record_names"):
        return {}
    import vmn_exp.registry.view as _rv  # lazy: keeps stamping paths clean
    refs = _rv.registered_runs(storage)
    _REASON = "registered as a model version; use `vmn-exp model delete` first"
    return {
        m["verstr"]: _REASON
        for m in candidates
        if (app_name, m["verstr"]) in refs
    }


def skip_message(verstr, status):
    if status == STUCK:
        return (
            f"Skipping {verstr}: stuck (its heartbeat is late; it may still be "
            "running — use --force to delete it)"
        )
    return f"Skipping {verstr}: still running (use --force to delete it)"


def tag_skip_message(verstr, tag_name):
    return (
        f"Skipping {verstr}: protected by tag '{tag_name}' "
        "(use --force to delete it)"
    )

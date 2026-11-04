#!/usr/bin/env python3
"""Keeping a parent's child markers (:mod:`vmn_exp.storage.child_markers`)
— and the app's "every child is marked" flag — in step with its children:
best-effort, never failing the write that called."""
from vmn_exp._base import VMN_LOGGER


def parent_of(metadata):
    parent = (metadata or {}).get("parent")
    return parent if parent and parent != metadata.get("verstr") else None


def _best_effort(storage, method, app_name, metadata):
    parent = parent_of(metadata)
    call = getattr(storage, method, None)
    if not parent or call is None:
        return False
    try:
        return call(app_name, parent, metadata["verstr"]) is not False
    except Exception:
        VMN_LOGGER.debug(f"{method} {metadata['verstr']} in {parent} failed", exc_info=True)
        return False


def mark_parent(storage, app_name, metadata):
    """Mark the run *metadata* describes in its parent's record; whether a
    marker was written. A child left unmarked drops the app's completeness
    flag, so the next targeted prune rescans the app's parent links."""
    marked = _best_effort(storage, "mark_child", app_name, metadata)
    if not marked and parent_of(metadata):
        _drop_complete(storage, app_name)
    return marked


def _drop_complete(storage, app_name):
    if not getattr(storage, "has_child_markers", False):
        return
    try:
        storage.set_children_complete(app_name, False)
    except Exception:
        VMN_LOGGER.debug(f"Dropping {app_name}'s child-marker flag failed", exc_info=True)


def unmark_parent(storage, app_name, metadata):
    """Drop the run's marker from its parent's record."""
    _best_effort(storage, "unmark_child", app_name, metadata)

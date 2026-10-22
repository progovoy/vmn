#!/usr/bin/env python3
"""What an S3 call's key is, as one of the fixed :data:`KINDS` (so a table
keyed by kind stays bounded): the store layout's areas (``runs/``,
``journal/``, ...) and, inside a run's record, which file it is."""

RUN_LISTING = "run listing"
CHILDREN_LISTING = "children listing"
OTHER = "other"
_RUN_FILES = {"metadata.yml": "metadata.yml", "run_state.yml": "run_state.yml"}
_RUN_DIRS = {"children": "child marker", "outputs": "outputs", "artifacts": "artifacts"}
_AREAS = ("journal", "comments", "reports", "code", "snapshots", "registry", "sweeps")
KINDS = frozenset((
    *_RUN_FILES.values(), *_RUN_DIRS.values(), *_AREAS, RUN_LISTING, CHILDREN_LISTING,
    "log segment", "metric stream", "metric index (.vmx)", "run file", "store.yml", OTHER,
))


def classify(operation, key):
    """The kind of the object (or, for a ``List*`` call, the prefix) *key*."""
    parts = key.split("/")
    if parts[-1] == "store.yml":
        return "store.yml"
    for i, part in enumerate(parts):
        if part == "runs":
            return _run_kind(operation, parts[i + 1:])
        if part in _AREAS:
            return part
    return OTHER


def _run_kind(operation, parts):
    """*parts* after ``runs/``: ``<app>/<verstr>/<file...>``."""
    inner = parts[2:]
    if operation.startswith("List"):
        return CHILDREN_LISTING if inner[:1] == ["children"] else RUN_LISTING
    if not inner:
        return OTHER
    head, leaf = inner[0], inner[-1]
    if len(inner) == 1:
        return _RUN_FILES.get(leaf, "run file")
    if head == "log":
        return "log segment"
    if head == "metrics":
        return "metric index (.vmx)" if leaf.endswith(".vmx") else "metric stream"
    return _RUN_DIRS.get(head, "run file")

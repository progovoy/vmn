"""The top-level areas of a store root (docs/plans/14-store-layout.md §2).

Every backend lays a root out the same way: ``<root>/<area>/<scope>/<name>/``,
the scope being an app key (tag form, ``/`` -> ``-``), a model name, ...
"""
import os

RUNS = "runs"
SNAPSHOTS = "snapshots"
CODE = "code"
SWEEPS = "sweeps"
REGISTRY = "registry"
REPORTS = "reports"
COMMENTS = "comments"
JOURNAL = "journal"

# An object store URI without a path keeps its areas under this root.
DEFAULT_ROOT = "vmn"


def local_store_root(repo_root):
    """The repo-local store root of the checkout at *repo_root*."""
    return os.path.join(repo_root, ".vmn", "store")


def app_key(app_name):
    """The scope segment of *app_name*: its tag form (``-`` is illegal in app
    names, so the mapping is bijective)."""
    return app_name.replace("/", "-")


def app_name_of(key):
    return key.replace("-", "/")


def area_prefix(root, area):
    return f"{root or DEFAULT_ROOT}/{area}"

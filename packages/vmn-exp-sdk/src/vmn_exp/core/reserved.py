"""Reserved pseudo-app names that must not appear in user-visible listings.

The model registry still keeps its records under the ``vmn-registry``
pseudo-app of the runs area (code objects and sweep claims have their own
store areas, :mod:`vmn_exp.storage.areas`). It must never surface in
``vmn-exp list``, the UI app chooser, or any other place that enumerates
experiment apps.
"""

RESERVED_APPS: frozenset = frozenset({"vmn-registry"})


def is_reserved_app(name: str) -> bool:
    """Return True if *name* is a reserved pseudo-app or lives under one
    (``vmn-registry/<x>``, or its tag form ``vmn-registry-<x>``). Real app
    names cannot contain ``-``, so neither form is ambiguous."""
    return any(
        name == app or name.startswith((app + "/", app + "-")) for app in RESERVED_APPS
    )

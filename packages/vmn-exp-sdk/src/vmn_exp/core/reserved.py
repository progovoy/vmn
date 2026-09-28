"""Reserved pseudo-app names that must not appear in user-visible listings.

These are synthetic app identifiers used internally by vmn features (e.g. the
model registry uses the ``vmn-registry`` pseudo-app).  They should never
surface in ``vmn-exp list``, the UI app chooser, or any other place that
enumerates experiment apps.

The constant is defined here — in the experiment-side core — so that every
listing function can import it without creating a circular dependency.
``vmn_exp/registry`` may reuse it once the package split lands.
"""

RESERVED_APPS: frozenset = frozenset({"vmn-registry"})


def is_reserved_app(name: str) -> bool:
    """Return True if *name* is a reserved pseudo-app (e.g. ``vmn-registry``)."""
    return name in RESERVED_APPS

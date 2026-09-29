"""Code objects: a dirty tree's patches + untracked tarball, stored once per identity.

A mirror of ``vmn_exp.core.code_store`` (see its docstring for the design):
records of the reserved pseudo-app ``vmn-code/<app~>`` of the experiment-subdir
store, keyed ``<code_verstr>.<full diff hash>``; ``metadata.yml`` (written
last, ``verstr`` = key) is the completion marker carrying the payload summary.
*storage* is any store with ``save``/``load_metadata``/``load_record``
(``LocalRecordStore`` or a vmn-exp backend).

Public: ``CODE_APP``, ``CODE_MISSING``, ``code_app(app) -> str``,
``code_key(code_verstr, diff_hash) -> str``,
``stored_code(storage, app, key) -> dict | None``,
``store_code(storage, app, key, payload, summary)``,
``publish_code(storage, app, key)`` (calls ``storage.mirror_record`` if any),
``resolve_code(storage, app, metadata, patches) -> (metadata, patches)``.
"""
CODE_APP = "vmn-code"
# Set (never stored) on a record whose code object is gone or incomplete.
CODE_MISSING = "code_missing"


def code_app(app_name):
    """The pseudo-app holding *app_name*'s code objects (one path segment)."""
    return f"{CODE_APP}/{app_name.replace('/', '~')}"


def code_key(code_verstr, diff_hash):
    return f"{code_verstr}.{diff_hash}"


def stored_code(storage, app_name, key):
    """The payload summary of *key*'s complete code object, or None."""
    marker = storage.load_metadata(code_app(app_name), key)
    return None if marker is None else {k: v for k, v in marker.items() if k != "verstr"}


def store_code(storage, app_name, key, payload, summary):
    """Write *key*'s code object: the *payload* files, then the marker."""
    storage.save(code_app(app_name), key, dict(summary, verstr=key), payload)


def publish_code(storage, app_name, key):
    """Upload *key*'s code object when only a local cache holds it."""
    mirror = getattr(storage, "mirror_record", None)
    if mirror is not None:
        mirror(code_app(app_name), key)


def resolve_code(storage, app_name, metadata, patches):
    """``(metadata, patches)`` with the code object's patches in place of the
    record's own; an unusable object gives empty patches and ``CODE_MISSING``."""
    key = (metadata or {}).get("code")
    if not key:
        return metadata, patches
    found, code_patches = storage.load_record(code_app(app_name), key)
    if found is None:
        return dict(metadata, **{CODE_MISSING: True}), {}
    return metadata, code_patches

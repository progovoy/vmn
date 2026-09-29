"""A run's code, stored once per code identity.

The patches and untracked tarball of a dirty tree are the same for every run
of that tree, so they live in one *code object* rather than in each run
record. Code objects are records of a reserved pseudo-app of the same store
(``vmn-code/<app>``), so every backend stores, syncs, lists and deletes them
with the machinery it already has, and they never show up as runs or apps.

A code object is keyed ``<code_verstr>.<full diff hash>``: the code verstr
ties it to its runs by name (prune matches a code's runs and objects by that
prefix), the full hash makes a collision of the verstr's 7-character hash
harmless. Its ``metadata.yml`` is the completion marker — written after the
payload, as for any record (its ``verstr`` is the key) — and carries the
payload summary a run copies (``has_*`` flags, ``untracked_skipped``). An
object without it counts as missing.

Writers of one identity store identical content, so a concurrent rewrite is
harmless: each file is replaced atomically, the marker only follows a full
payload, and last writer wins.
"""
CODE_APP = "vmn-code"
# Set (never stored) on a run whose code object is gone or incomplete.
CODE_MISSING = "code_missing"


def code_app(app_name):
    """The pseudo-app holding *app_name*'s code objects (one path segment)."""
    return f"{CODE_APP}/{app_name.replace('/', '~')}"


def code_key(code_verstr, diff_hash):
    return f"{code_verstr}.{diff_hash}"


def stored_code(storage, app_name, key):
    """The payload summary of *key*'s complete code object, or None when
    there is none."""
    marker = storage.load_metadata(code_app(app_name), key)
    return None if marker is None else {k: v for k, v in marker.items() if k != "verstr"}


def store_code(storage, app_name, key, payload, summary):
    """Write *key*'s code object: the *payload* files, then the marker."""
    storage.save(code_app(app_name), key, dict(summary, verstr=key), payload)


def publish_code(storage, app_name, key):
    """Upload *key*'s code object to the remote when only the local cache
    holds it (``stored_code`` reads local-first): a run created there must
    not point at a code object the remote lacks."""
    mirror = getattr(storage, "mirror_record", None)
    if mirror is not None:
        mirror(code_app(app_name), key)


def resolve_code(storage, app_name, metadata, patches):
    """``(metadata, patches)`` of a run record with its code object's patches
    in place of its own; a run whose object is unusable gets empty patches
    and :data:`CODE_MISSING` set."""
    key = (metadata or {}).get("code")
    if not key:
        return metadata, patches
    found, code_patches = storage.load_record(code_app(app_name), key)
    if found is None:
        return dict(metadata, **{CODE_MISSING: True}), {}
    return metadata, code_patches


def drop_unused_code(storage, app_name, code_verstrs):
    """Delete the code objects of *code_verstrs* no run of the app still uses
    — complete or not. Called after runs are deleted, so a code object goes
    with the last run of its code."""
    code_verstrs = set(code_verstrs) - {None}
    if not code_verstrs:
        return
    doomed = code_verstrs - _dot_prefixes(storage.list_record_names(app_name))
    if not doomed:
        return
    for key in storage.list_record_names(code_app(app_name)):
        if key.rsplit(".", 1)[0] in doomed:
            storage.delete(code_app(app_name), key)


def _dot_prefixes(names):
    """Every ``.``-bounded prefix of *names*: a run ``<code verstr>.r2`` (or
    ``.<writer id>``) yields its code verstr among them."""
    prefixes = set()
    for name in names:
        parts = name.split(".")
        prefixes.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return prefixes

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
from vmn_exp.storage.areas import CODE

# Set (never stored) on a run whose code object is gone or incomplete.
CODE_MISSING = "code_missing"


def code_storage(storage):
    """The ``code`` area of *storage*'s root (records keyed by app)."""
    return storage.in_area(CODE)


def code_key(code_verstr, diff_hash):
    return f"{code_verstr}.{diff_hash}"


def stored_code(storage, app_name, key):
    """The payload summary of *key*'s complete code object, or None when
    there is none."""
    marker = code_storage(storage).load_metadata(app_name, key)
    return None if marker is None else {k: v for k, v in marker.items() if k != "verstr"}


def store_code(storage, app_name, key, payload, summary):
    """Write *key*'s code object: the *payload* files, then the marker."""
    code_storage(storage).save(app_name, key, dict(summary, verstr=key), payload)


def copy_code(src, dst, app_name, key):
    """Copy *key*'s code object from *src* to *dst* (payload, then marker);
    False when *src* has no such object."""
    marker, payload = code_storage(src).load_record(app_name, key)
    if marker is None:
        return False
    code_storage(dst).save(app_name, key, marker, payload)
    return True


def publish_code(storage, app_name, key):
    """Upload *key*'s code object to the remote when only the local cache
    holds it (``stored_code`` reads local-first): a run created there must
    not point at a code object the remote lacks."""
    mirror = getattr(code_storage(storage), "mirror_record", None)
    if mirror is not None:
        mirror(app_name, key)


def resolve_code(storage, app_name, metadata, patches):
    """``(metadata, patches)`` of a run record with its code object's patches
    in place of its own; a run whose object is unusable gets empty patches
    and :data:`CODE_MISSING` set."""
    key = (metadata or {}).get("code")
    if not key:
        return metadata, patches
    found, code_patches = code_storage(storage).load_record(app_name, key)
    if found is None:
        return dict(metadata, **{CODE_MISSING: True}), {}
    return metadata, code_patches


def find_code_key(storage, app_name, code_verstr):
    """The key of the one complete code object of *code_verstr*, or None when
    there is none or more than one (a ``from_snapshot`` run names only its
    code verstr)."""
    keys = [
        key for key in code_storage(storage).list_record_names(app_name)
        if key.rsplit(".", 1)[0] == code_verstr
        and stored_code(storage, app_name, key) is not None
    ]
    return keys[0] if len(keys) == 1 else None


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
    for key in code_storage(storage).list_record_names(app_name):
        if key.rsplit(".", 1)[0] in doomed:
            code_storage(storage).delete(app_name, key)


def _dot_prefixes(names):
    """Every ``.``-bounded prefix of *names*: a run ``<code verstr>.r2`` (or
    ``.<writer id>``) yields its code verstr among them."""
    prefixes = set()
    for name in names:
        parts = name.split(".")
        prefixes.update(".".join(parts[:i]) for i in range(1, len(parts) + 1))
    return prefixes

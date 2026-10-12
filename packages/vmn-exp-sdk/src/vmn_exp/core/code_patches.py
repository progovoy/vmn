"""The text patches of a run's code, read file by file.

``storage.load`` resolves a run's whole code object, untracked tarball
included (see :mod:`vmn_exp.core.code_store`). What the code *says* — the
files, functions and commits it changes (:mod:`vmn_exp.core.features`) — is
in the text patches alone, so these read only ``working_tree.patch`` and
``local_commits.patch``, the run's own and each dep's (``deps/<safe dep
name>/``), through ``load_file``.

The result has the shape of ``storage.load``'s patches minus the tarballs:
``{"working_tree", "local_commits", "deps": {dep path: {...}}}``, the keys
present only for the patches found.

A read that comes back empty-handed is checked against the store's listing of
the record (its own files; a dep's are not listed): a file the store lists
but cannot read — a backend that answers None for any error, S3 among them —
is a :class:`CodeReadError`, never taken for one that is not there.
"""
from vmn_exp.core.code_store import code_storage, stored_code
from vmn_exp.storage.files import METADATA_FILE, PATCH_FILES, safe_dep_name

_TEXT_PATCHES = tuple((key, name) for key, name, binary in PATCH_FILES if not binary)


class CodeReadError(RuntimeError):
    """A file the store lists could not be read (a transient failure)."""


def code_patch_texts(storage, app_name, key, dep_paths=()):
    """The text patches of *key*'s code object, or None when it is missing
    or incomplete (its marker is not listed). *dep_paths* are the run's deps
    (a code object does not name them); none is read when the object holds
    no dep patches."""
    summary = stored_code(storage, app_name, key)
    if summary is None:
        if METADATA_FILE in _listed(code_storage(storage), app_name, key):
            raise CodeReadError(f"could not read code object {key}")
        return None
    if summary.get("has_dep_patches") is False:
        dep_paths = ()
    return record_patch_texts(code_storage(storage), app_name, key, dep_paths)


def unreadable_code_keys(storage, app_name, code_verstr, names=None):
    """The code objects of *code_verstr* whose marker the store lists but
    cannot read (``find_code_key`` counts them as missing). *names*: the
    code area's record names, already listed."""
    area = code_storage(storage)
    if names is None:
        names = area.list_record_names(app_name)
    keys = [key for key in names if key.rsplit(".", 1)[0] == code_verstr]
    listed = area.list_files(app_name, keys=keys) if keys else {}
    return [key for key in keys if METADATA_FILE in (listed.get(key) or ())
            and stored_code(storage, app_name, key) is None]


def record_patch_texts(storage, app_name, verstr, dep_paths=()):
    """The text patches *storage*'s record *verstr* holds itself."""
    patches, unread = _texts(storage, app_name, verstr, "")
    failed = sorted(set(unread) & _listed(storage, app_name, verstr)) if unread else ()
    if failed:
        raise CodeReadError(f"could not read {', '.join(failed)} of {verstr}")
    deps = {}
    for dep_path in sorted(set(dep_paths)):
        found, _ = _texts(storage, app_name, verstr, f"deps/{safe_dep_name(dep_path)}/")
        if found:
            deps[dep_path] = found
    if deps:
        patches["deps"] = deps
    return patches


def run_dep_paths(metadata):
    """The dep paths of a run's *metadata*: its ``dep_base_commits`` keys and,
    for records from before them too, its ``changesets`` keys but ``.``."""
    deps = set(metadata.get("dep_base_commits") or ()) | set(metadata.get("changesets") or ())
    return sorted(deps - {"."})


def patch_items(patches):
    """*patches* as ``features_from_patches`` input: the run's own texts, then
    each dep's as ``(dep path, text)``, deps by path."""
    deps = patches.get("deps") or {}
    sources = [(None, patches)] + [(path, deps[path]) for path in sorted(deps)]
    return [
        text if prefix is None else (prefix, text)
        for prefix, source in sources
        for key, _ in _TEXT_PATCHES
        for text in [source.get(key)]
        if text
    ]


def _texts(storage, app_name, verstr, prefix):
    """``(texts found, names read as None)`` of the text patches at *prefix*."""
    found, unread = {}, []
    for key, name in _TEXT_PATCHES:
        data = storage.load_file(app_name, verstr, prefix + name)
        if data is None:
            unread.append(prefix + name)
        elif data:
            found[key] = data.decode("utf-8", errors="replace")
    return found, unread


def _listed(storage, app_name, verstr):
    """The names of the files *storage* lists for its record *verstr*."""
    return set(storage.list_files(app_name, keys=[verstr]).get(verstr) or ())

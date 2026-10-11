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
"""
from vmn_exp.core.code_store import code_storage, stored_code
from vmn_exp.storage.files import PATCH_FILES, safe_dep_name

_TEXT_PATCHES = tuple((key, name) for key, name, binary in PATCH_FILES if not binary)


def code_patch_texts(storage, app_name, key, dep_paths=()):
    """The text patches of *key*'s code object, or None when it is missing
    or incomplete. *dep_paths* are the run's deps (a code object does not
    name them); none is read when the object holds no dep patches."""
    summary = stored_code(storage, app_name, key)
    if summary is None:
        return None
    if summary.get("has_dep_patches") is False:
        dep_paths = ()
    return record_patch_texts(code_storage(storage), app_name, key, dep_paths)


def record_patch_texts(storage, app_name, verstr, dep_paths=()):
    """The text patches *storage*'s record *verstr* holds itself."""
    patches = _texts(storage, app_name, verstr, "")
    deps = {}
    for dep_path in sorted(set(dep_paths)):
        found = _texts(storage, app_name, verstr, f"deps/{safe_dep_name(dep_path)}/")
        if found:
            deps[dep_path] = found
    if deps:
        patches["deps"] = deps
    return patches


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
    found = {}
    for key, name in _TEXT_PATCHES:
        data = storage.load_file(app_name, verstr, prefix + name)
        if data:
            found[key] = data.decode("utf-8", errors="replace")
    return found

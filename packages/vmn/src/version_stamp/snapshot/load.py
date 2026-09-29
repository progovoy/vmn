"""Load the tree a snapshot command works on: a record with its code, or a
stamped version.

Public:
  - ``load_snapshot(stores, app_name, verstr, action) -> (metadata, patches) | None``
    — logs why not: no such record, or its code object is gone
    (``CODE_MISSING``; *action* names what cannot be done, e.g. ``restore``).
  - ``stamped_state(vcs, version) -> (metadata, {}) | None`` — a stamped
    version as a snapshot of its app commit, with no patches.
"""
from version_stamp.core.logging import VMN_LOGGER
from version_stamp.snapshot.code_store import CODE_MISSING


def load_snapshot(stores, app_name, verstr, action):
    metadata, patches = stores.records.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return None
    if metadata.get(CODE_MISSING):
        VMN_LOGGER.error(
            f"Cannot {action} snapshot {verstr}: its code object "
            f"({metadata.get('code')}) is missing from the store"
        )
        return None
    return metadata, patches


def _stamped_ver_info(vcs, version):
    try:
        tag_name, ver_infos = vcs.get_version_info_from_verstr(version)
    except Exception:
        VMN_LOGGER.debug(f"Failed to resolve stamped version {version}", exc_info=True)
        return None
    found = ver_infos.get(tag_name) if ver_infos else None
    return found["ver_info"] if found else None


def stamped_state(vcs, version):
    if "-dev." in version:
        return None
    ver_info = _stamped_ver_info(vcs, version)
    if ver_info is None:
        return None
    changesets = ver_info["stamping"]["app"].get("changesets", {})
    app_repo = changesets.get(".", {})
    if not app_repo.get("hash"):
        return None
    metadata = {
        "verstr": version,
        "base_version": version,
        "base_commit": app_repo["hash"],
        "remote": app_repo.get("remote"),
        "app_name": vcs.name,
        "changesets": changesets,
    }
    return metadata, {}

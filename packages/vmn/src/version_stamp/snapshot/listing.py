"""``vmn snapshot list|show|note``: read (and annotate) snapshot records.

``list`` numbers rows by storage index (oldest first) — what ``@N`` resolves
— whatever ``--last`` / ``--filter`` hide. ``--json`` prints the same rows
(``index`` + metadata) or, for ``show``, ``{"metadata", "patches"}`` with the
untracked tarballs as member lists.

Public:
  - ``relative_timestamp(iso_ts) -> str`` (``"2m ago"``; the input on failure).
  - ``snapshot_list(records, app_name, last=None, filters=None, verbose=False,
    as_json=False) -> int``.
  - ``snapshot_show(records, app_name, verstr, as_json=False) -> int``.
  - ``snapshot_note(records, app_name, verstr, note) -> int``.
"""
import datetime
import json

import yaml

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.devversion.untracked import _list_tarball_members

_UNITS = ((86400, "d"), (3600, "h"), (60, "m"))


def relative_timestamp(iso_ts):
    try:
        dt = datetime.datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        seconds = int((datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds())
    except Exception:
        VMN_LOGGER.debug("Failed to parse timestamp %s", iso_ts, exc_info=True)
        return iso_ts
    if seconds < 0:
        return iso_ts
    for size, unit in _UNITS:
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return f"{seconds}s ago"


def _matches(meta, filters):
    user_meta = meta.get("user_meta") or {}
    return all(str(user_meta.get(k)) == v for k, v in (filters or {}).items())


def _numbered_rows(records, app_name, last, filters):
    numbered = list(enumerate(records.list_snapshots(app_name), 1))
    if last:
        numbered = numbered[-last:]
    return [(idx, meta) for idx, meta in numbered if _matches(meta, filters)]


def _row_line(idx, meta, verbose):
    stamp = meta.get("timestamp", "")
    shown = stamp if verbose else relative_timestamp(stamp)
    note = f" - {meta['note']}" if meta.get("note") else ""
    user_meta = meta.get("user_meta") or {}
    pairs = "".join(f" {k}={v}" for k, v in user_meta.items())
    return f"[{idx}] {meta['verstr']}  ({shown}){note}{pairs}"


def _print_json(value):
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def snapshot_list(records, app_name, last=None, filters=None, verbose=False, as_json=False):
    rows = _numbered_rows(records, app_name, last, filters)
    if as_json:
        _print_json([dict(meta, index=idx) for idx, meta in rows])
        return 0
    if not rows:
        VMN_LOGGER.info(f"No snapshots found for {app_name}")
    for idx, meta in rows:
        print(_row_line(idx, meta, verbose))
    return 0


def _patches_for_json(patches):
    shown = {k: v for k, v in patches.items() if k != "deps" and not isinstance(v, bytes)}
    if patches.get("untracked_files"):
        shown["untracked_files"] = _list_tarball_members(patches["untracked_files"])
    if patches.get("deps"):
        shown["deps"] = {dep: _patches_for_json(dp) for dep, dp in patches["deps"].items()}
    return shown


def _print_patches(patches):
    if patches.get("working_tree"):
        print("--- Working tree patch ---")
        print(patches["working_tree"])
    if patches.get("local_commits"):
        print("--- Local commits patch ---")
        print(patches["local_commits"])
    if patches.get("untracked_files"):
        print("--- Untracked files ---")
        for name in _list_tarball_members(patches["untracked_files"]):
            print(f"  {name}")


def _print_dep_patches(deps):
    for dep_name, dp in deps.items():
        print(f"\n--- Dep: {dep_name} ---")
        for key, label in (("working_tree", "working tree"), ("local_commits", "local commits")):
            if dp.get(key):
                print(f"  {label} patch: {len(dp[key])} bytes")
        if dp.get("untracked_files"):
            count = len(_list_tarball_members(dp["untracked_files"]))
            print(f"  untracked files: {count} files")


def snapshot_show(records, app_name, verstr, as_json=False):
    metadata, patches = records.load(app_name, verstr)
    if metadata is None:
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
    if as_json:
        _print_json({"metadata": metadata, "patches": _patches_for_json(patches)})
        return 0
    print(yaml.dump(metadata, sort_keys=True))
    _print_patches(patches)
    _print_dep_patches(patches.get("deps") or {})
    return 0


def snapshot_note(records, app_name, verstr, note):
    if note is None:
        VMN_LOGGER.error("Must specify --note")
        return 1
    if not records.update_note(app_name, verstr, note):
        VMN_LOGGER.error(f"Snapshot {verstr} not found")
        return 1
    VMN_LOGGER.info(f"Updated note for {verstr}")
    return 0

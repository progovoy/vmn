"""``vmn snapshot create``: save the dirty tree as a thin record.

The record (``.vmn/<app>/snapshots/<verstr>/metadata.yml``, or the configured
store's) holds identity and metadata only; the patches and untracked tarball
live once in the shared code store and are referenced as ``code:``. The code
object is built only when the store has no complete one for this identity.

Re-creating a state already saved keeps its record — same verstr, same
``timestamp``, so its ``@N`` stays put — and only updates ``note`` /
``user_meta`` when given.

Public:
  - ``parse_meta_args(["k=v", ...]) -> dict`` (ValueError on a bad item).
  - ``build_user_meta(meta_args, meta_file) -> dict | None``.
  - ``snapshot_verstr(records, app_name, captured) -> str``.
  - ``store_snapshot(vcs, stores, captured, verstr, note=None, user_meta=None)
    -> (summary, created)`` — never touches an existing record.
  - ``snapshot_create(vcs, stores, note=None, user_meta=None, status=None) -> int``;
    prints the verstr as its last stdout line.
"""
import sys

import yaml

from version_stamp.core.logging import VMN_LOGGER
from version_stamp.snapshot.capture import capture_identity, ensure_code
from version_stamp.snapshot.identity import _unique_snapshot_verstr
from version_stamp.snapshot.record import build_record_metadata

CLEAN_TREE = "No local changes to snapshot (working tree is clean)"


def parse_meta_args(meta_list):
    result = {}
    for item in meta_list or ():
        if "=" not in item:
            raise ValueError(f"Invalid --meta format: {item}. Expected key=value")
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _read_meta_file(meta_file):
    with open(meta_file) as f:
        file_meta = yaml.safe_load(f)
    if not isinstance(file_meta, dict):
        raise ValueError(
            f"--meta-file must contain a YAML mapping, got {type(file_meta).__name__}"
        )
    return file_meta


def build_user_meta(meta_args, meta_file):
    result = _read_meta_file(meta_file) if meta_file else {}
    result.update(parse_meta_args(meta_args))
    return result or None


def _changesets(captured):
    return captured.ver_info["stamping"]["app"].get("changesets", {})


def _new_record(vcs, verstr, captured, code, summary, note, user_meta):
    metadata = build_record_metadata(
        vcs, verstr, captured.base_version, captured.commit_hash,
        captured.dirty_states, captured.identity, captured.ver_info,
        note=note, code=(code, summary), diff_hash=captured.diff_hash,
    )
    if user_meta:
        metadata["user_meta"] = user_meta
    return metadata


def _refresh_existing(records, app_name, verstr, note, user_meta):
    updates = {"note": note, "user_meta": user_meta}
    updates = {k: v for k, v in updates.items() if v is not None}
    if updates:
        records.update_metadata(app_name, verstr, updates)


def _warn_skipped(summary):
    skipped = summary.get("untracked_skipped")
    if skipped:
        VMN_LOGGER.warning(
            f"Untracked files left out of the snapshot (over the size caps): "
            f"{', '.join(skipped)}. Raise VMN_SNAPSHOT_MAX_FILE_MB / "
            "VMN_SNAPSHOT_MAX_TOTAL_MB to include them."
        )


def snapshot_verstr(records, app_name, captured):
    """The verstr *captured* is (or would be) saved under in *records*."""
    return _unique_snapshot_verstr(
        records, app_name, captured.base_version, captured.commit_hash,
        captured.diff_hash, _changesets(captured),
    )


def store_snapshot(vcs, stores, captured, verstr, note=None, user_meta=None):
    """Store *captured*'s code object and, unless *verstr* already exists, its
    record. ``(payload summary, created)``."""
    code, summary = ensure_code(stores.code, vcs, captured)
    created = not stores.records.exists(vcs.name, verstr)
    if created:
        metadata = _new_record(vcs, verstr, captured, code, summary, note, user_meta)
        stores.records.save(vcs.name, verstr, metadata, {})
    return summary, created


def snapshot_create(vcs, stores, note=None, user_meta=None, status=None):
    captured, err = capture_identity(vcs, status=status)
    if err is not None:
        return err
    if not captured.diff_hash:
        print(CLEAN_TREE, file=sys.stderr)
        return 0

    verstr = snapshot_verstr(stores.records, vcs.name, captured)
    summary, created = store_snapshot(vcs, stores, captured, verstr, note, user_meta)
    if not created:
        _refresh_existing(stores.records, vcs.name, verstr, note, user_meta)
    _warn_skipped(summary)
    VMN_LOGGER.info(f"Created snapshot: {verstr}")
    print(verstr)
    return 0

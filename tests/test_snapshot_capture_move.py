"""Snapshot capture lives in vmn (``version_stamp.snapshot.capture``).

vmn-exp's ``gitmode.capture`` is a shim over the facade names, and a dev
verstr is only reused for the same diff *and* the same repo commits.
"""
import importlib

from version_stamp import api
from version_stamp.devversion.capture import _unique_snapshot_verstr
from version_stamp.snapshot.local_store import LocalRecordStore

APP = "my_app"
BASE, COMMIT = "0.0.1", "abcdef1234567"
DIFF_HASH = "1234567" + "a" * 57
SHORT = f"{BASE}-dev.abcdef1.1234567"
CHANGESETS = {".": {"hash": "aaa"}, "../dep": {"hash": "bbb"}}

_FACADE = {
    "SnapshotCapture": ("version_stamp.snapshot.capture", "SnapshotCapture"),
    "capture_identity": ("version_stamp.snapshot.capture", "capture_identity"),
    "ensure_code": ("version_stamp.snapshot.capture", "ensure_code"),
    "build_record_metadata": ("version_stamp.snapshot.record", "build_record_metadata"),
    "patch_summary": ("version_stamp.snapshot.record", "patch_summary"),
    "open_snapshot_stores": ("version_stamp.snapshot.stores", "open_snapshot_stores"),
    "register_snapshot_store_opener": (
        "version_stamp.cli.plugin_api",
        "register_snapshot_store_opener",
    ),
    "LocalRecordStore": ("version_stamp.snapshot.local_store", "LocalRecordStore"),
}


def test_facade_exposes_snapshot_names():
    for name, (module, attr) in _FACADE.items():
        assert name in api.__all__
        assert getattr(api, name) is getattr(importlib.import_module(module), attr)


def test_gitmode_capture_is_the_vmn_capture():
    from vmn_exp.gitmode import capture

    assert capture.Capture is api.SnapshotCapture
    assert capture.capture_snapshot is api.capture_identity
    assert capture.ensure_code is api.ensure_code


def _stored(tmp_path, changesets=CHANGESETS):
    store = LocalRecordStore(str(tmp_path))
    meta = {"verstr": SHORT, "diff_hash": DIFF_HASH, "changesets": changesets}
    store.save(APP, SHORT, meta, {"working_tree": "diff\n"})
    return store


def test_same_diff_new_dep_commit_gets_a_new_verstr(tmp_path):
    store = _stored(tmp_path)
    moved = dict(CHANGESETS, **{"../dep": {"hash": "ccc"}})

    same = _unique_snapshot_verstr(
        store, APP, BASE, COMMIT, DIFF_HASH, changesets=CHANGESETS
    )
    new = _unique_snapshot_verstr(store, APP, BASE, COMMIT, DIFF_HASH, changesets=moved)

    assert same == SHORT
    assert new == f"{BASE}-dev.abcdef1.{DIFF_HASH[:12]}"


def test_legacy_callers_without_changesets_keep_old_behaviour(tmp_path):
    store = _stored(tmp_path)

    assert _unique_snapshot_verstr(store, APP, BASE, COMMIT, DIFF_HASH) == SHORT
    other = "7654321" + "b" * 57
    assert _unique_snapshot_verstr(store, APP, BASE, COMMIT, other) == (
        f"{BASE}-dev.abcdef1.7654321"
    )

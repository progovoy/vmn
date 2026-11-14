"""vmn's shared-directory store (``LocalRecordStore.at_root``) writes the same
record files as vmn-exp-sdk's ``LocalSnapshotStorage`` on the same root, but
for ``format_version``: core stamps 1, the SDK 2 (by design)."""
import os

import yaml

from vmn_exp.storage.local import LocalSnapshotStorage
from version_stamp.snapshot.local_store import LocalRecordStore

APP = "root_app/svc"
VERSTR = "0.0.1-dev.abcdef1.1234567"
PATCHES = {
    "working_tree": "diff --git a/f b/f\n+x\n",
    "untracked_files": b"\x1f\x8bTAR",
    "deps": {"../dep": {"local_commits": "From abc\n"}},
}
METADATA = {
    "verstr": VERSTR,
    "timestamp": "2026-01-01T00:00:00Z",
    "note": "n",
    "diff_hash": "1234567" + "0" * 57,
}


def _tree(root):
    found = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                found[os.path.relpath(path, root)] = f.read()
    return found


def _saved(tmp_path):
    ours, theirs = str(tmp_path / "core"), str(tmp_path / "sdk")
    LocalRecordStore.at_root(ours, "snapshots").save(APP, VERSTR, dict(METADATA), PATCHES)
    LocalSnapshotStorage(theirs, "snapshots").save(APP, VERSTR, dict(METADATA), PATCHES)
    return _tree(ours), _tree(theirs)


def _metadata_path():
    return os.path.join("snapshots", "root_app-svc", VERSTR, "metadata.yml")


def test_record_files_are_byte_identical_but_metadata(tmp_path):
    ours, theirs = _saved(tmp_path)
    meta = _metadata_path()
    assert ours.keys() == theirs.keys()
    assert {k: v for k, v in ours.items() if k != meta} == {
        k: v for k, v in theirs.items() if k != meta
    }


def test_metadata_differs_only_in_format_version(tmp_path):
    ours, theirs = _saved(tmp_path)
    meta = _metadata_path()
    core, sdk = yaml.safe_load(ours[meta]), yaml.safe_load(theirs[meta])
    assert (core.pop("format_version"), sdk.pop("format_version")) == (1, 2)
    assert core == sdk == METADATA
    assert ours[meta] == theirs[meta].replace(b"format_version: 2", b"format_version: 1")

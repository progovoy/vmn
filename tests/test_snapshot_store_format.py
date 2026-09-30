"""Two-way contract: vmn's snapshot store writes what vmn-exp-sdk reads, and back.

``version_stamp`` may not import ``vmn_exp``, so the record and code-object
format lives on both sides; these tests keep the copies byte-compatible.
"""
import os

import yaml

from vmn_exp.core import code_store as sdk_code
from vmn_exp.storage import files as sdk_files
from vmn_exp.storage.local import LocalSnapshotStorage
from version_stamp.snapshot import code_store as vmn_code
from version_stamp.snapshot import identity
from version_stamp.snapshot import record as vmn_record
from version_stamp.snapshot.local_store import LocalRecordStore

APP = "root_app/svc"
VERSTR = "0.0.1-dev.abcdef1.1234567"
PATCHES = {
    "working_tree": "diff --git a/f b/f\n+x\n",
    "untracked_files": b"\x1f\x8bTAR",
    "deps": {"../dep": {"local_commits": "From abc\n"}},
}


def _metadata(verstr=VERSTR, **extra):
    return dict(
        verstr=verstr,
        timestamp="2026-01-01T00:00:00Z",
        note="n",
        diff_hash="1234567" + "0" * 57,
        **extra,
    )


def _record_files(root, subdir, app, verstr):
    rec = os.path.join(root, ".vmn", *app.split("/"), subdir, verstr)
    found = {}
    for dirpath, _, filenames in os.walk(rec):
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as f:
                found[os.path.relpath(path, rec)] = f.read()
    return found


def test_vmn_record_reads_back_in_vmn_exp_storage(tmp_path):
    root = str(tmp_path)
    LocalRecordStore(root, "snapshots").save(APP, VERSTR, _metadata(), PATCHES)

    sdk = LocalSnapshotStorage(root, "snapshots")
    metadata, patches = sdk.load_record(APP, VERSTR)
    assert metadata == _metadata()
    assert patches["working_tree"] == PATCHES["working_tree"]
    assert patches["untracked_files"] == PATCHES["untracked_files"]
    assert patches["deps"] == {".._dep": {"local_commits": "From abc\n"}}
    assert [m["verstr"] for m in sdk.list_snapshots(APP)] == [VERSTR]
    base = os.path.join(root, ".vmn", "root_app", "svc", "snapshots")
    with open(os.path.join(base, ".gitignore")) as f:
        assert f.read() == "*\n"


def test_vmn_and_vmn_exp_write_identical_bytes(tmp_path):
    ours, theirs = str(tmp_path / "a"), str(tmp_path / "b")
    LocalRecordStore(ours, "snapshots").save(APP, VERSTR, _metadata(), PATCHES)
    LocalSnapshotStorage(theirs, "snapshots").save(APP, VERSTR, _metadata(), PATCHES)
    assert _record_files(ours, "snapshots", APP, VERSTR) == _record_files(
        theirs, "snapshots", APP, VERSTR
    )


def test_vmn_exp_record_reads_back_in_vmn_store(tmp_path):
    root = str(tmp_path)
    LocalSnapshotStorage(root, "snapshots").save(APP, VERSTR, _metadata(), PATCHES)

    store = LocalRecordStore(root, "snapshots")
    metadata, patches = store.load_record(APP, VERSTR)
    assert metadata == _metadata()
    assert patches["untracked_files"] == PATCHES["untracked_files"]
    assert "deps" in patches
    assert store.load_metadata(APP, VERSTR) == _metadata()
    assert store.exists(APP, VERSTR)
    assert store.list_verstrs(APP) == [VERSTR]
    assert [m["verstr"] for m in store.list_snapshots(APP)] == [VERSTR]


def test_code_object_written_by_vmn_is_stored_code_for_exp(tmp_path):
    root = str(tmp_path)
    key = vmn_code.code_key(VERSTR, "f" * 64)
    summary = {"has_working_tree_patch": True, "has_untracked_files": True}
    vmn_code.store_code(LocalRecordStore(root, "experiments"), APP, key, PATCHES, summary)

    sdk = LocalSnapshotStorage(root, "experiments")
    assert sdk_code.stored_code(sdk, APP, key) == summary
    assert sdk_code.find_code_key(sdk, APP, VERSTR) == key
    assert os.path.isdir(os.path.join(root, ".vmn", "vmn-code", "root_app~svc", "experiments"))


def test_code_object_written_by_exp_resolves_in_vmn(tmp_path):
    root = str(tmp_path)
    key = sdk_code.code_key(VERSTR, "f" * 64)
    sdk_code.store_code(LocalSnapshotStorage(root, "experiments"), APP, key, PATCHES, {})
    LocalSnapshotStorage(root, "snapshots").save(APP, VERSTR, _metadata(code=key), {})

    code = LocalRecordStore(root, "experiments")
    records = LocalRecordStore(root, "snapshots", code_store=code)
    assert vmn_code.stored_code(code, APP, key) == {}
    metadata, patches = records.load(APP, VERSTR)
    assert metadata["code"] == key
    assert patches["working_tree"] == PATCHES["working_tree"]


def test_missing_code_object_is_flagged(tmp_path):
    root = str(tmp_path)
    records = LocalRecordStore(root, "snapshots", code_store=LocalRecordStore(root, "experiments"))
    records.save(APP, VERSTR, _metadata(code="nope.x"), {})
    metadata, patches = records.load(APP, VERSTR)
    assert metadata[vmn_code.CODE_MISSING] is True
    assert patches == {}


def test_code_store_constants_match_the_sdk():
    assert vmn_code.CODE_APP == sdk_code.CODE_APP
    assert vmn_code.CODE_MISSING == sdk_code.CODE_MISSING
    assert vmn_code.code_app(APP) == sdk_code.code_app(APP)
    assert vmn_code.code_key("v", "h") == sdk_code.code_key("v", "h")
    assert vmn_record.METADATA_FILE == sdk_files.METADATA_FILE
    assert vmn_record.PATCH_FILES == sdk_files.PATCH_FILES
    assert identity.safe_dep_name("a/b") == sdk_files.safe_dep_name("a/b")


def test_verinfo_dir_is_not_a_record(tmp_path):
    root = str(tmp_path)
    verinfo = os.path.join(root, ".vmn", "app", "snapshots", "0.0.1")
    os.makedirs(verinfo)
    with open(os.path.join(verinfo, "metadata.yml"), "w") as f:
        yaml.dump({"vmn_info": {}, "stamping": {}}, f)

    for store in (LocalRecordStore(root, "snapshots"), LocalSnapshotStorage(root, "snapshots")):
        assert store.list_snapshots("app") == []
        assert store.load_metadata("app", "0.0.1") is None


def test_plus_in_verstr_round_trips(tmp_path):
    root = str(tmp_path)
    verstr = "0.0.1+build-dev.abcdef1.1234567"
    LocalRecordStore(root, "snapshots").save("app", verstr, _metadata(verstr), {})
    assert os.path.isdir(
        os.path.join(root, ".vmn", "app", "snapshots", identity.safe_verstr(verstr))
    )
    assert identity.safe_verstr(verstr) == sdk_files.safe_verstr(verstr)
    assert LocalSnapshotStorage(root, "snapshots").list_verstrs("app") == [verstr]
    LocalSnapshotStorage(root, "snapshots").save("app", "1+x", _metadata("1+x"), {})
    assert sorted(LocalRecordStore(root, "snapshots").list_verstrs("app")) == sorted(
        [verstr, "1+x"]
    )


def test_update_note_and_delete(tmp_path):
    root = str(tmp_path)
    store = LocalRecordStore(root, "snapshots")
    store.save(APP, VERSTR, _metadata(), PATCHES)
    assert store.update_note(APP, VERSTR, "new") is True
    assert store.update_metadata(APP, VERSTR, {"user_meta": {"k": "v"}, "note": None})
    meta = LocalSnapshotStorage(root, "snapshots").load_metadata(APP, VERSTR)
    assert meta["user_meta"] == {"k": "v"} and "note" not in meta
    assert store.update_note(APP, "missing", "x") is False
    store.delete(APP, VERSTR)
    assert not store.exists(APP, VERSTR)
    assert store.load_record(APP, VERSTR) == (None, None)


def test_list_snapshots_orders_by_timestamp(tmp_path):
    store = LocalRecordStore(str(tmp_path), "snapshots")
    store.save("app", "b", dict(_metadata("b"), timestamp="2026-02-01T00:00:00Z"), {})
    store.save("app", "a", dict(_metadata("a"), timestamp="2026-03-01T00:00:00Z"), {})
    assert [m["verstr"] for m in store.list_snapshots("app")] == ["b", "a"]
    assert sorted(store.list_record_names("app")) == ["a", "b"]
    assert store.list_snapshots("other") == []


def test_patch_summary_matches_vmn_exp():
    from vmn_exp.snapshot import _patch_summary

    patches = dict(PATCHES, untracked_skipped=["big.bin"])
    patches["deps"] = {"../dep": {"untracked_skipped": ["x"]}}
    assert vmn_record.patch_summary(patches) == _patch_summary(patches)
    assert vmn_record.patch_summary(patches)["untracked_skipped"] == ["big.bin", "../dep/x"]


def test_build_record_metadata_carries_the_code_verstr():
    from types import SimpleNamespace

    backend = SimpleNamespace(active_branch="main", remote=lambda: "git@x:r")
    vcs = SimpleNamespace(backend=backend, name="app")
    ver_info = {"stamping": {"app": {"changesets": {".": {"hash": "c" * 40}}}}}
    meta = vmn_record.build_record_metadata(
        vcs, "0.0.1-dev.abcdef1.1234567abcd", "0.0.1", "abcdef1" + "0" * 33,
        ["modified"], {"working_tree": "diff\n"}, ver_info, note="hi",
    )
    assert meta["verstr"] == "0.0.1-dev.abcdef1.1234567abcd"
    assert meta["code_verstr"] == "0.0.1-dev.abcdef1." + meta["diff_hash"][:7]
    assert len(meta["diff_hash"]) == 64
    assert meta["branch"] == "main" and meta["remote"] == "git@x:r"
    assert meta["note"] == "hi" and meta["has_working_tree_patch"] is True
    assert meta["changesets"] == {".": {"hash": "c" * 40}}

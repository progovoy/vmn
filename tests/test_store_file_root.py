"""``LocalRecordStore.at_root``: a record store on a shared directory
(``file://``, NFS) laid out ``<root>/<kind>/<app-key>/<safe verstr>/``."""
import os

from version_stamp.snapshot.local_store import LocalRecordStore
from version_stamp.store import marker

APP = "root_app/svc"
VERSTR = "0.0.1-dev.abcdef1.1234567+x"
PATCHES = {
    "working_tree": "diff --git a/f b/f\n+x\n",
    "untracked_files": b"\x1f\x8bTAR",
    "deps": {"../dep": {"local_commits": "From abc\n"}},
}


def _metadata(verstr=VERSTR):
    return {"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z", "note": "n"}


def _files(top):
    return sorted(
        os.path.relpath(os.path.join(d, n), top) for d, _, names in os.walk(top) for n in names
    )


def test_at_root_writes_the_store_root_layout(tmp_path):
    root = str(tmp_path / "shared")
    LocalRecordStore.at_root(root, "snapshots").save(APP, VERSTR, _metadata(), PATCHES)
    rec = os.path.join("snapshots", "root_app-svc", "0.0.1-dev.abcdef1.1234567_plus_x")
    assert _files(root) == [
        ".gitignore",
        os.path.join(rec, "deps", ".._dep", "local_commits.patch"),
        os.path.join(rec, "metadata.yml"),
        os.path.join(rec, "untracked_files.tar.gz"),
        os.path.join(rec, "working_tree.patch"),
    ]
    with open(os.path.join(root, ".gitignore")) as f:
        assert f.read() == "*\n"


def test_at_root_round_trips_save_load_list_delete(tmp_path):
    store = LocalRecordStore.at_root(str(tmp_path), "runs")
    store.save(APP, VERSTR, _metadata(), PATCHES)
    metadata, patches = store.load(APP, VERSTR)
    assert metadata == dict(_metadata(), format_version=1)
    assert patches["untracked_files"] == PATCHES["untracked_files"]
    assert patches["deps"] == {".._dep": {"local_commits": "From abc\n"}}
    assert store.exists(APP, VERSTR)
    assert store.list_verstrs(APP) == [VERSTR]
    assert [m["verstr"] for m in store.list_snapshots(APP)] == [VERSTR]
    assert store.update_note(APP, VERSTR, "m")
    assert store.load_metadata(APP, VERSTR)["note"] == "m"
    store.delete(APP, VERSTR)
    assert not store.exists(APP, VERSTR)
    assert store.load_record(APP, VERSTR) == (None, None)


def test_at_root_resolves_code_through_its_code_store(tmp_path):
    code = LocalRecordStore.at_root(str(tmp_path), "code")
    code.save(APP, "c.1", {"verstr": "c.1"}, {"working_tree": "code diff\n"})
    store = LocalRecordStore.at_root(str(tmp_path), "snapshots", code_store=code)
    store.save(APP, VERSTR, dict(_metadata(), code="c.1"), {})
    assert store.load(APP, VERSTR)[1] == {"working_tree": "code diff\n"}


def test_at_root_adopts_no_v1_layout(tmp_path):
    v1 = tmp_path / ".vmn" / "root_app" / "svc" / "snapshots" / "old"
    v1.mkdir(parents=True)
    (v1 / "metadata.yml").write_text("verstr: old\n")
    store = LocalRecordStore.at_root(str(tmp_path), "snapshots")
    assert store.list_verstrs(APP) == []
    store.save(APP, VERSTR, _metadata(), {})
    assert (v1 / "metadata.yml").is_file()
    assert store.list_verstrs(APP) == [VERSTR]


def test_at_root_exposes_root_and_area(tmp_path):
    store = LocalRecordStore.at_root(str(tmp_path), "snapshots")
    assert (store.root, store.area) == (str(tmp_path), "snapshots")


def test_marker_root_of_an_at_root_store_is_a_local_root(tmp_path):
    where = marker.root_of(LocalRecordStore.at_root(str(tmp_path), "snapshots"))
    assert isinstance(where, marker.LocalRoot)
    assert where.root == str(tmp_path)


def test_the_repo_local_store_is_no_marker_root(tmp_path):
    assert marker.root_of(LocalRecordStore(str(tmp_path), "snapshots")) is None

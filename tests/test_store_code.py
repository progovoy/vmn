"""``version_stamp.store.code``: code objects over any record store (a fake here)."""
from version_stamp.snapshot import code_store
from version_stamp.store import code


class FakeRecords:
    """In-memory ``save``/``load_metadata``/``load_record``."""

    def __init__(self):
        self.records = {}

    def save(self, app_name, verstr, metadata, patches):
        self.records[(app_name, verstr)] = (dict(metadata, format_version=1), patches)

    def load_metadata(self, app_name, verstr):
        found = self.records.get((app_name, verstr))
        return None if found is None else found[0]

    def load_record(self, app_name, verstr):
        return self.records.get((app_name, verstr), (None, None))


class MirroringRecords(FakeRecords):
    def __init__(self):
        super().__init__()
        self.mirrored = []

    def mirror_record(self, app_name, key):
        self.mirrored.append((app_name, key))


def test_code_key_joins_verstr_and_diff_hash():
    assert code.code_key("0.0.1-dev.abc.1234567", "f" * 64) == "0.0.1-dev.abc.1234567." + "f" * 64


def test_a_stored_code_object_gives_back_its_summary():
    store = FakeRecords()
    code.store_code(store, "app", "k", {"working_tree": "d\n"}, {"has_working_tree_patch": True})
    assert store.records[("app", "k")][0]["verstr"] == "k"
    assert code.stored_code(store, "app", "k") == {"has_working_tree_patch": True}


def test_an_absent_code_object_has_no_summary():
    assert code.stored_code(FakeRecords(), "app", "k") is None


def test_publish_mirrors_only_when_the_store_can():
    store = MirroringRecords()
    code.publish_code(store, "app", "k")
    code.publish_code(FakeRecords(), "app", "k")
    assert store.mirrored == [("app", "k")]


def test_resolve_takes_the_code_objects_patches():
    store = FakeRecords()
    code.store_code(store, "app", "k", {"working_tree": "code\n"}, {})
    meta = {"code": "k"}
    assert code.resolve_code(store, "app", meta, {"working_tree": "own\n"}) == (
        meta, {"working_tree": "code\n"},
    )


def test_resolve_without_a_code_reference_keeps_the_record():
    meta, patches = {"verstr": "v"}, {"working_tree": "own\n"}
    assert code.resolve_code(FakeRecords(), "app", meta, patches) == (meta, patches)


def test_resolve_of_a_missing_code_object_marks_it():
    meta, patches = code.resolve_code(FakeRecords(), "app", {"code": "k"}, {"x": 1})
    assert meta == {"code": "k", code.CODE_MISSING: True}
    assert patches == {}


def test_snapshot_code_store_re_exports_the_store_code():
    for name in ("CODE_MISSING", "code_key", "stored_code", "store_code",
                 "publish_code", "resolve_code"):
        assert getattr(code_store, name) is getattr(code, name)

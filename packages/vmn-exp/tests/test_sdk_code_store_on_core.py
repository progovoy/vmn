"""``vmn_exp.core.code_store`` on core's ``version_stamp.store.code`` (plan 37
P5e): the SDK functions take any area and hop to the ``code`` area; their
behavior is pinned here with an in-memory fake."""
from version_stamp.store import code as core_code
from vmn_exp.core import code_store
from vmn_exp.storage.areas import CODE


class FakeArea:
    def __init__(self, records=None, mirror=False):
        self.records = dict(records or {})  # (app, key) -> (metadata, payload)
        self.saved, self.mirrored = [], []
        if mirror:
            self.mirror_record = lambda app, key: self.mirrored.append((app, key))

    def load_metadata(self, app, key):
        return self.records.get((app, key), (None, None))[0]

    def load_record(self, app, key):
        return self.records.get((app, key), (None, {}))

    def save(self, app, key, metadata, payload):
        self.saved.append((app, key, metadata, payload))


class FakeStorage:
    """A runs area whose ``in_area`` hands out *code*; only ``CODE`` is asked for."""

    def __init__(self, code):
        self.code, self.hops = code, []

    def in_area(self, name):
        self.hops.append(name)
        assert name == CODE
        return self.code


def test_code_key_and_code_missing_are_cores():
    assert code_store.code_key is core_code.code_key
    assert code_store.CODE_MISSING is core_code.CODE_MISSING


def test_stored_code_is_the_marker_without_verstr_and_format_version():
    marker = {"verstr": "k", "format_version": 2, "has_patch": True, "untracked_skipped": []}
    storage = FakeStorage(FakeArea({("app", "k"): (marker, {})}))
    assert code_store.stored_code(storage, "app", "k") == {"has_patch": True, "untracked_skipped": []}
    assert code_store.stored_code(storage, "app", "other") is None
    assert storage.hops == [CODE, CODE]


def test_store_code_saves_the_summary_with_the_key_as_verstr():
    area = FakeArea()
    code_store.store_code(FakeStorage(area), "app", "k", {"a.patch": b"x"}, {"has_patch": True})
    assert area.saved == [("app", "k", {"has_patch": True, "verstr": "k"}, {"a.patch": b"x"})]


def test_publish_code_mirrors_through_the_code_area_when_it_can():
    area = FakeArea(mirror=True)
    code_store.publish_code(FakeStorage(area), "app", "k")
    assert area.mirrored == [("app", "k")]
    code_store.publish_code(FakeStorage(FakeArea()), "app", "k")  # no mirror: a no-op


def test_resolve_code_without_a_code_key_never_opens_the_code_area():
    storage = FakeStorage(FakeArea())
    assert code_store.resolve_code(storage, "app", {"x": 1}, {"own": b"p"}) == ({"x": 1}, {"own": b"p"})
    assert code_store.resolve_code(storage, "app", None, {"own": b"p"}) == (None, {"own": b"p"})
    assert storage.hops == []


def test_resolve_code_takes_the_code_objects_patches():
    storage = FakeStorage(FakeArea({("app", "k"): ({"verstr": "k"}, {"c.patch": b"c"})}))
    meta = {"code": "k"}
    assert code_store.resolve_code(storage, "app", meta, {"own": b"p"}) == (meta, {"c.patch": b"c"})


def test_resolve_code_of_a_missing_object_flags_it_and_empties_the_patches():
    storage = FakeStorage(FakeArea())
    meta, patches = code_store.resolve_code(storage, "app", {"code": "k"}, {"own": b"p"})
    assert meta == {"code": "k", code_store.CODE_MISSING: True}
    assert patches == {}

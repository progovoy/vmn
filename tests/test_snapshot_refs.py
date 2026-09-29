"""vmn's ``resolve_snapshot_ref`` behaves exactly like vmn-exp's ``_resolve_verstr``."""
import pytest

from vmn_exp.core.resolve_ref import _resolve_verstr
from version_stamp.snapshot.local_store import LocalRecordStore
from version_stamp.snapshot.refs import resolve_snapshot_ref

RESOLVERS = pytest.mark.parametrize("resolve", [resolve_snapshot_ref, _resolve_verstr])

OLD = "0.0.1-dev.abcdef1.1111111"
MID = "0.0.1-dev.abcdef1.1112222"
NEW = "0.0.1-dev.fedcba9.3333333"


@pytest.fixture
def store(tmp_path):
    store = LocalRecordStore(str(tmp_path), "snapshots")
    for day, verstr in enumerate((OLD, MID, NEW), start=1):
        meta = {"verstr": verstr, "timestamp": f"2026-01-0{day}T00:00:00Z"}
        store.save("app", verstr, meta, {})
    return store


@RESOLVERS
def test_latest(resolve, store):
    assert resolve(store, "app", None, latest=True) == (NEW, None)
    assert resolve(store, "app", "latest") == (NEW, None)
    assert resolve(store, "app", "@latest") == (NEW, None)


@RESOLVERS
def test_latest_of_no_snapshots(resolve, store):
    assert resolve(store, "other", "latest") == (None, "No snapshots found for other")


@RESOLVERS
def test_at_index(resolve, store):
    assert resolve(store, "app", "@1") == (OLD, None)
    assert resolve(store, "app", "@3") == (NEW, None)


@RESOLVERS
@pytest.mark.parametrize("ref", ["@0", "@4"])
def test_at_index_out_of_range(resolve, store, ref):
    assert resolve(store, "app", ref) == (None, f"Index '{ref}' out of range (1..3)")


@RESOLVERS
def test_at_index_not_a_number(resolve, store):
    verstr, err = resolve(store, "app", "@x")
    assert verstr is None and "Invalid index reference '@x'" in err


@RESOLVERS
def test_exact_and_unique_prefix(resolve, store):
    assert resolve(store, "app", MID) == (MID, None)
    assert resolve(store, "app", "0.0.1-dev.fed") == (NEW, None)


@RESOLVERS
def test_ambiguous_prefix(resolve, store):
    verstr, err = resolve(store, "app", "0.0.1-dev.abcdef1.111")
    assert verstr is None
    assert err == (
        "Ambiguous prefix '0.0.1-dev.abcdef1.111': matches 2 snapshots: "
        f"{OLD}, {MID}"
    )


@RESOLVERS
def test_unknown_dev_version(resolve, store):
    assert resolve(store, "app", "0.0.1-dev.0000000") == (
        None,
        "Snapshot '0.0.1-dev.0000000' not found",
    )


@RESOLVERS
def test_stamped_version_passes_through(resolve, store):
    assert resolve(store, "app", "1.2.3") == ("1.2.3", None)
    assert resolve(store, "app", None) == (None, None)

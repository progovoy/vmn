"""SnapshotStorage, not the local module behind it, is the filesystem interface
for store data (plan 44 G14): the same port calls pass on in-memory buckets."""
import pytest

from object_store_fakes import FakeContainerClient, FakeGCSClient, MatchConditions

APP = "trainer"
VERSTR = "1.2.0-dev.abc1234.0000001"
META = {"verstr": VERSTR, "app": APP, "format_version": 1}


def _gcs():
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    return GCSSnapshotStorage("bkt", prefix="p", client=FakeGCSClient())


def _azure():
    from vmn_exp.storage.azure import AzureSnapshotStorage

    return AzureSnapshotStorage(
        "bkt", prefix="p", container=FakeContainerClient("bkt"),
        if_not_modified=MatchConditions.IfNotModified,
    )


@pytest.mark.parametrize("make_store", [_gcs, _azure], ids=["gs", "az"])
def test_a_record_written_through_the_storage_port_reads_back_on_the_in_memory_bucket_fakes(
    make_store, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    store = make_store()

    assert store.create_exclusive(APP, VERSTR, META, {"working_tree": "diff"})

    assert store.list_apps() == [APP]
    assert store.list_verstrs(APP) == [VERSTR]
    metadata, patches = store.load(APP, VERSTR)
    assert metadata == META and patches["working_tree"] == "diff"
    assert list(tmp_path.iterdir()) == []  # no local store directory

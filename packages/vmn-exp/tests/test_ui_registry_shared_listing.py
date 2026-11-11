"""The lineage snapshot and the Models list snapshot each list the registry
(a listing per model) on refresh; with background refresh they share one
listing per refresh. A listing younger than ``REFRESH_SEC`` is reused, a
write through the UI drops it, and a snapshot built from a reused listing is
as old as it (its next refresh lists anew). Without background refresh each
request still lists, so it sees every write."""
import pytest

pytest.importorskip("fastapi")

from models_registry_fixture import (  # noqa: E402
    MODELS, build_registry, registry_reads, store_client, store_storage,
)

from vmn_exp.registry.names import version_record_name  # noqa: E402
from vmn_exp.registry.store import register_version  # noqa: E402
from vmn_exp.ui import registry_snapshot  # noqa: E402
from vmn_exp.ui.readers.models import ModelListing  # noqa: E402
from vmn_exp.ui.registry_snapshot import (  # noqa: E402
    RegistryListings, RegistrySnapshot, RegistrySnapshots,
)


def _lists(tmp_path, background, monkeypatch):
    build_registry(store_storage(tmp_path), models=3, versions=2)
    app, client = store_client(tmp_path, background=background)
    reads = registry_reads(monkeypatch, names=("list_apps",))
    assert client.get(MODELS).status_code == 200
    assert client.get(f"{MODELS}/m001/versions/1/lineage").status_code == 200
    if background:
        app.state.refresher.stop()
    return len(reads.calls)


def test_with_background_refresh_both_snapshots_share_one_listing(tmp_path, monkeypatch):
    assert _lists(tmp_path, True, monkeypatch) == 1


def test_without_background_refresh_each_request_lists(tmp_path, monkeypatch):
    assert _lists(tmp_path, False, monkeypatch) == 2


def _pair(storage):
    listings = RegistryListings()
    return (listings, RegistrySnapshots(True, RegistrySnapshot.read, listings),
            RegistrySnapshots(True, ModelListing.read, listings))


def test_a_write_through_the_ui_drops_the_shared_listing(tmp_path, monkeypatch):
    storage = store_storage(tmp_path)
    build_registry(storage, models=2, versions=1)
    listings, lineage, models = _pair(storage)
    lineage.get(storage)
    models.get(storage)
    register_version(storage, "m000", {"app": "app", "verstr": "1.0.5"})
    models.refresh_model(storage, "m000")
    reads = registry_reads(monkeypatch, names=("list_apps",))
    _, listing = listings.get(storage)
    assert reads.calls == ["list_apps"]
    assert version_record_name(2) in listing["m000"]


def test_a_listing_a_write_dropped_while_in_flight_is_taken_again(tmp_path, monkeypatch):
    storage = store_storage(tmp_path)
    listings = RegistryListings()
    taken = iter([{"old": {}}, {"new": {}}])

    def list_registry(storage):
        listing = next(taken)
        if "old" in listing:
            listings.forget(storage)
        return listing

    monkeypatch.setattr(registry_snapshot, "list_registry", list_registry)
    assert listings.get(storage)[1] == {"new": {}}
    assert listings.get(storage)[1] == {"new": {}}


def test_a_snapshot_of_a_reused_listing_is_as_old_as_it(tmp_path):
    storage = store_storage(tmp_path)
    build_registry(storage, models=1, versions=1)
    listings, lineage, models = _pair(storage)
    lineage.get(storage)
    models.get(storage)
    at, _ = listings.get(storage)
    assert lineage._entry(storage).at == models._entry(storage).at == at

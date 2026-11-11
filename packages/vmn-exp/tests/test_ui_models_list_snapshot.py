"""The Models page reads the registry from a background-refreshed snapshot:
on fgm's S3 store (241 models, 7.7k versions) each list request walked the
registry one model at a time (~45 s). A warm request reads no store; the
snapshot's reads run concurrently; a write through the UI shows at once."""
import time

import pytest

pytest.importorskip("fastapi")

from models_registry_fixture import (  # noqa: E402
    MODELS, build_registry, registry_reads, store_client, store_storage,
)

from vmn_exp.registry.store import ensure_model, register_version  # noqa: E402
from vmn_exp.ui import registry_snapshot  # noqa: E402

RECORD_READS = ("load_file", "load_logs_by_writer")  # a model's header, log, versions


@pytest.fixture
def served(tmp_path):
    storage = store_storage(tmp_path)
    build_registry(storage, models=3, versions=4, aliased=1)
    app, client = store_client(tmp_path, background=True)
    yield storage, client
    app.state.refresher.stop()


def test_the_list_rows_match_the_registry(served):
    _, client = served
    rows = client.get(MODELS).json()["models"]
    assert [r["name"] for r in rows] == ["m000", "m001", "m002"]
    first = rows[0]
    assert first["kind"] == "model"
    assert (first["latest_version"], first["versions_count"]) == (4, 4)
    assert first["aliases"] == {"prod": 4}
    assert first["updated"] == "2026-01-01T00:04:00Z"
    assert rows[1]["aliases"] == {}
    assert client.get(MODELS, params={"kind": "dataset"}).json() == {"models": []}


def test_a_warm_list_reads_no_registry(served, monkeypatch):
    _, client = served
    cold = client.get(MODELS).json()
    reads = registry_reads(monkeypatch)
    assert client.get(MODELS).json() == cold
    assert reads.calls == []


def test_a_version_registered_through_the_ui_lists_at_once(served):
    _, client = served
    client.get(MODELS)
    r = client.post(f"{MODELS}/m001/versions", json={"run": {"app": "app", "verstr": "1.0.9"}})
    assert r.status_code == 201
    row = {m["name"]: m for m in client.get(MODELS).json()["models"]}["m001"]
    assert (row["latest_version"], row["versions_count"]) == (5, 5)


def test_another_writer_shows_after_a_background_refresh(served, monkeypatch):
    storage, client = served
    client.get(MODELS)
    monkeypatch.setattr(registry_snapshot, "REFRESH_SEC", 0.0)
    ensure_model(storage, "newcomer")
    register_version(storage, "newcomer", {"app": "app", "verstr": "1.0.1"})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if "newcomer" in [m["name"] for m in client.get(MODELS).json()["models"]]:
            return
        time.sleep(0.05)
    pytest.fail("the new model never listed")


def test_the_list_reads_the_registry_concurrently(tmp_path, monkeypatch):
    build_registry(store_storage(tmp_path), models=6, versions=2)
    _, client = store_client(tmp_path, background=False)
    reads = registry_reads(monkeypatch, latency=0.02, names=RECORD_READS)
    assert len(client.get(MODELS).json()["models"]) == 6
    assert reads.peak > 1


def test_a_model_detail_reads_its_versions_concurrently(tmp_path, monkeypatch):
    build_registry(store_storage(tmp_path), models=1, versions=6)
    _, client = store_client(tmp_path, background=False)
    reads = registry_reads(monkeypatch, latency=0.02)
    detail = client.get(f"{MODELS}/m000").json()
    assert [v["version"] for v in detail["versions"]] == [1, 2, 3, 4, 5, 6]
    assert reads.peak > 1


def test_the_lineage_snapshot_reads_versions_concurrently(tmp_path, monkeypatch):
    from vmn_exp.ui.registry_snapshot import RegistrySnapshot

    storage = store_storage(tmp_path)
    build_registry(storage, models=1, versions=6)
    reads = registry_reads(monkeypatch, latency=0.02)
    snapshot = RegistrySnapshot.read(storage)
    assert snapshot.version("m000", 6)["n"] == 6
    assert reads.peak > 1

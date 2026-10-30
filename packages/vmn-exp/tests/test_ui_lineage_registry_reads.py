"""Lineage routes read the model registry from a background-refreshed view:
once warm, a run's or a version's lineage request reads nothing of the
registry area (no listing, no ``metadata.yml``, no log) — on S3 the walk was
1,630 GETs and 336 listings per request."""
import pytest
from exp_helpers import _storage
from test_ui_lineage_api import _chain, _get

from vmn_exp.registry.log import record_use
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.areas import REGISTRY

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

MODELS = "/api/v1/workspaces/main/models"
READS = ("list_apps", "list_files", "list_record_names", "load_file", "load_merged_log",
         "load_logs_by_writer", "load_record")


@pytest.fixture
def background(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(f"{app_layout.base_dir}/ui_data")
    manager.attach_path("main", app_layout.repo_path)
    _chain(app_layout)
    storage = _storage(app_layout)
    ensure_model(storage, "clf")
    register_version(storage, "clf", {"app": app_layout.app_name, "verstr": "0.0.1-exp.train"},
                     artifact_path="model.pkl")
    record_use(storage, "clf", 1, app_layout.app_name, "0.0.1-exp.eval")
    app = create_app(manager, background_refresh=True)
    yield TestClient(app)
    app.state.refresher.stop()


@pytest.fixture
def registry_reads(monkeypatch):
    seen = []
    for name in READS:
        original = getattr(LocalSnapshotStorage, name, None)
        if original is None:
            continue

        def counted(self, *args, _original=original, _name=name, **kwargs):
            if self.area == REGISTRY:
                seen.append(_name)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(LocalSnapshotStorage, name, counted)
    return seen


def _lineages(client, app_layout):
    run = _get(client, app_layout, "0.0.1-exp.eval").json()
    version = client.get(f"{MODELS}/clf/versions/1/lineage").json()
    return run, version


def test_warm_lineage_requests_read_no_registry(background, app_layout, registry_reads):
    cold = _lineages(background, app_layout)
    link = cold[0]["upstream"][0]["links"][0]
    assert (link["model"], link["version"]) == ("clf", 1)
    assert cold[1]["producer"]["verstr"] == "0.0.1-exp.train"
    assert [c["verstr"] for c in cold[1]["consumers"]] == ["0.0.1-exp.eval"]
    registry_reads.clear()

    assert _lineages(background, app_layout) == cold
    assert registry_reads == []


def test_a_refresh_rereads_only_the_changed_models(app_layout):
    from vmn_exp.ui.registry_snapshot import RegistrySnapshot

    storage = _storage(app_layout)
    for name in ("a", "b"):
        ensure_model(storage, name)
        register_version(storage, name, {"app": app_layout.app_name, "verstr": f"0.0.1-exp.{name}"})
    first = RegistrySnapshot.read(storage)
    record_use(storage, "a", 1, app_layout.app_name, "0.0.1-exp.use")

    second = RegistrySnapshot.read(storage, first)
    assert [u["verstr"] for u in second.uses("a", 1)] == ["0.0.1-exp.use"]
    assert first.uses("a", 1) == []
    assert second._models["b"] is first._models["b"]
    assert [m["model"] for m in second.models_of(app_layout.app_name, "0.0.1-exp.b")] == ["b"]

"""The registry lives in the store's ``registry`` area: scope = model name,
records ``header``, ``v<N>`` and ``uses`` (docs/plans/14-store-layout.md §2)."""
import os

from vmn_exp.registry.log import record_use, set_alias
from vmn_exp.registry.store import ensure_model, list_models, list_versions, register_version
from vmn_exp.storage.local import LocalSnapshotStorage


def _runs(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def test_model_records_live_under_registry_scope(tmp_path):
    storage = _runs(tmp_path)
    ensure_model(storage, "resnet")
    register_version(storage, "resnet", {"app": "app", "verstr": "1.0.0"})
    set_alias(storage, "resnet", "prod", 1)
    record_use(storage, "resnet", 1, "app", "1.0.0")
    scope = tmp_path / "registry" / "resnet"
    assert sorted(os.listdir(scope)) == ["header", "uses", "v1"]
    assert not (tmp_path / "runs").exists() or not os.listdir(tmp_path / "runs")
    assert list_models(storage) == ["resnet"]
    assert list_versions(storage, "resnet") == [1]


def test_list_apps_never_returns_registry_scopes(tmp_path):
    storage = _runs(tmp_path)
    ensure_model(storage, "resnet")
    register_version(storage, "resnet", {"app": "app", "verstr": "1.0.0"})
    storage.save("myapp", "1.0.0", {"verstr": "1.0.0"}, {})
    assert storage.list_apps() == ["myapp"]
    assert storage.in_area("registry").list_apps() == ["resnet"]

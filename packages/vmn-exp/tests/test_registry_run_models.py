"""Which model versions came from a run: one scan of the registry per registry
change, shared by every lookup (the lineage route asks per request) and by
prune's registered_runs."""
from vmn_exp.registry import view
from vmn_exp.registry.log import set_alias, set_version_status
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.storage.local import LocalSnapshotStorage


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def _ref(verstr, app="myapp"):
    return {"app": app, "verstr": verstr}


def _registry(storage):
    ensure_model(storage, "clf")
    register_version(storage, "clf", _ref("1.0.0"))
    register_version(storage, "clf", _ref("2.0.0"))
    ensure_model(storage, "det")
    register_version(storage, "det", _ref("1.0.0"))


def _count_version_reads(monkeypatch):
    reads = []
    real = view.get_version

    def counting(storage, model, n):
        reads.append((model, n))
        return real(storage, model, n)

    monkeypatch.setattr(view, "get_version", counting)
    return reads


def test_models_for_run_lists_every_live_version_of_the_run(tmp_path):
    storage = _storage(tmp_path)
    _registry(storage)
    set_alias(storage, "clf", "prod", 1)
    found = view.models_for_run(storage, "myapp", "1.0.0")
    assert [(m["model"], m["version"], m["aliases"]) for m in found] == [
        ("clf", 1, ["prod"]), ("det", 1, []),
    ]
    assert view.models_for_run(storage, "myapp", "9.9.9") == []


def test_lookups_reuse_one_scan_until_the_registry_changes(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _registry(storage)
    reads = _count_version_reads(monkeypatch)
    view.models_for_run(storage, "myapp", "1.0.0")
    scanned = len(reads)
    view.models_for_run(storage, "myapp", "2.0.0")
    assert view.registered_runs(storage) == {("myapp", "1.0.0"), ("myapp", "2.0.0")}
    assert len(reads) == scanned

    set_version_status(storage, "clf", 2, "deleted")
    assert view.models_for_run(storage, "myapp", "2.0.0") == []
    assert view.registered_runs(storage) == {("myapp", "1.0.0")}
